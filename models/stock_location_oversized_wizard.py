# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError

class StockLocationOversizedWizard(models.TransientModel):
    _name = 'wb.stock.location.oversized.wizard'
    _description = 'Wizard para Sobredimensionar Ubicación'

    original_location_id = fields.Many2one('stock.location', string='Ubicación Original', required=True)
    location_ids = fields.Many2many(
        'stock.location', 
        string='Ubicaciones a Bloquear', 
        required=True,
        domain="[('id', '!=', original_location_id), ('original_parent_id', '=', False), ('usage', '=', 'internal'), ('is_empty_location', '=', True)]"
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_model = self.env.context.get('active_model')
        active_id = self.env.context.get('active_id')
        if active_model == 'stock.location' and active_id:
            res['original_location_id'] = active_id
        elif self.env.context.get('default_original_location_id'):
            res['original_location_id'] = self.env.context.get('default_original_location_id')
        return res

    def action_block_oversized(self):
        self.ensure_one()

        if not self.env.user.has_group('stock.group_stock_user'):
            raise UserError("Solo un Operador de inventario puede realizar esta acción.")

        # Check that we are not blocking the original location itself
        if self.original_location_id in self.location_ids:
            raise UserError("No se puede bloquear la ubicación original por sobredimensionado.")

        # Get blocked parent sub-child location
        xml_id = 'wb_tech_location_blocking.location_blocked_sobredimensionada'
        blocked_parent = self.env.ref(xml_id, raise_if_not_found=False)
        if not blocked_parent:
            blocked_parent = self.env['stock.location'].sudo().search([
                ('name', '=', 'Sobredimensionada'),
                ('location_id.name', '=', 'Bloqueado')
            ], limit=1)
        if not blocked_parent:
            raise UserError("No se encontró la ubicación de bloqueo correspondiente para Sobredimensionada.")

        for location in self.location_ids:
            if location.original_parent_id:
                raise UserError(f"La ubicación {location.complete_name} ya está bloqueada.")

            # Validation: Sin producto (si tiene, rechazar y pedir mover primero)
            quants = self.env['stock.quant'].sudo().search([
                ('location_id', '=', location.id),
                ('quantity', '>', 0)
            ], limit=1)
            
            if quants:
                raise UserError(f"La ubicación {location.complete_name} contiene producto. Debe mover el producto antes de bloquear la ubicación por el motivo seleccionado.")

            # Save original parent (its own parent before blocking) and block
            vals = {
                'location_id': blocked_parent.id,
                'block_reason_type': 'sobredimensionada',
                'block_reason': f"Bloqueado/Sobredimensionada - Ubicación Original: {self.original_location_id.complete_name}",
                'block_date': fields.Datetime.now(),
                'block_user_id': self.env.user.id,
                'original_parent_id': location.location_id.id,
                'oversized_from_location_id': self.original_location_id.id,
            }

            location.with_context(skip_history_write=True).sudo().write(vals)

            # Create history entry
            self.env['stock.location.block.history'].create({
                'location_id': location.id,
                'event_type': 'block',
                'block_reason_type': 'sobredimensionada',
                'block_reason': vals['block_reason'],
                'date': vals['block_date'],
                'user_id': vals['block_user_id'],
                'comment': f"Ubicación bloqueada por sobredimensionado apuntando a {self.original_location_id.complete_name}."
            })

        return {'type': 'ir.actions.act_window_close'}
