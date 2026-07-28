# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError

class StockLocationBlockWizard(models.TransientModel):
    _name = 'wb.stock.location.block.wizard'
    _description = 'Wizard para bloquear ubicación'

    location_ids = fields.Many2many('stock.location', string='Ubicaciones', required=True)
    
    block_reason_type = fields.Selection([
        ('no_apto', 'No Apta'),
        ('danado', 'Dañada'),
        ('onsite', 'Onsite'),
        ('dupla', 'Dupla')
    ], string='Motivo', required=True, default='no_apto')
    
    comment = fields.Text(string='Comentario')
    ticket = fields.Char(string='Ticket de Mantenimiento')
    expiration_date = fields.Date(string='Fecha de Expiración')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids')
        if active_model == 'stock.location' and active_ids:
            res['location_ids'] = [(6, 0, active_ids)]
        elif self.env.context.get('default_location_id'):
            res['location_ids'] = [(6, 0, [self.env.context.get('default_location_id')])]
        return res

    def action_block(self):
        self.ensure_one()

        # 1. Check permissions by reason type
        if self.block_reason_type == 'ciclico':
            raise UserError("No se puede bloquear por motivo Cíclico usando este asistente. Debe realizarse a través de WMDS.")
        elif self.block_reason_type in ('no_apto', 'danado', 'onsite', 'dupla'):
            if not self.env.user.has_group('wb_tech_location_blocking.group_lider_de_turno'):
                liders = self.env.ref('wb_tech_location_blocking.group_lider_de_turno').users.mapped('name')
                raise UserError(f"Solo el Líder de turno puede realizar esta acción. Solicita a alguno de los siguientes usuarios que bloqueen esta ubicación: {', '.join(liders)}")

        # 2. Process each location
        for location in self.location_ids:
            # Skip/raise if already blocked
            if location.original_parent_id:
                raise UserError(f"La ubicación {location.complete_name} ya está bloqueada.")

            if self.block_reason_type == 'ciclico':
                # Validation: Sin reservas activas, sin movimientos pendientes. Puede tener producto.
                pending_moves = self.env['stock.move.line'].sudo().search([
                    '|', ('location_id', '=', location.id), ('location_dest_id', '=', location.id),
                    ('state', 'not in', ['done', 'cancel'])
                ], limit=1)
                
                if pending_moves:
                    ref = pending_moves.picking_id.name or pending_moves.move_id.reference or 'un movimiento'
                    raise UserError(f"No se puede bloquear la ubicación {location.complete_name} por motivo Cíclico: tiene movimientos o reservas pendientes en {ref}.")

            elif self.block_reason_type in ('no_apto', 'danado', 'onsite', 'dupla'):
                # Validation: Sin producto (si tiene, rechazar y pedir mover primero)
                quants = self.env['stock.quant'].sudo().search([
                    ('location_id', '=', location.id),
                    ('quantity', '>', 0)
                ], limit=1)
                
                if quants:
                    reason_label = dict(self._fields['block_reason_type'].selection).get(self.block_reason_type)
                    raise UserError(f"La ubicación {location.complete_name} contiene producto. Debe mover el producto antes de bloquear la ubicación por el motivo {reason_label}.")

            # Get blocked parent sub-child location
            xml_id = f'wb_tech_location_blocking.location_blocked_{self.block_reason_type}'
            blocked_parent = self.env.ref(xml_id, raise_if_not_found=False)
            if not blocked_parent:
                # Fallback search by name
                sub_name = {
                    'ciclico': 'Ciclico',
                    'no_apto': 'NoApta',
                    'danado': 'Dañada',
                    'onsite': 'Onsite',
                    'dupla': 'Dupla'
                }.get(self.block_reason_type, 'Ciclico')
                
                blocked_parent = self.env['stock.location'].sudo().search([
                    ('name', '=', sub_name),
                    ('location_id.name', '=', 'Bloqueado')
                ], limit=1)
                
            if not blocked_parent:
                raise UserError(f"No se encontró la ubicación de bloqueo correspondiente para el motivo {self.block_reason_type}.")

            # Determine block_reason: use comment if provided, otherwise use the label of the reason type prefixed with "Bloqueado/"
            reason_label = dict(self._fields['block_reason_type'].selection).get(self.block_reason_type)
            block_reason_value = self.comment.strip() if self.comment and self.comment.strip() else f"Bloqueado/{reason_label}"

            # Save original parent and block
            vals = {
                'location_id': blocked_parent.id,
                'block_reason_type': self.block_reason_type,
                'block_reason': block_reason_value,
                'block_date': fields.Datetime.now(),
                'block_user_id': self.env.user.id,
                'block_ticket': self.ticket if self.block_reason_type in ('no_apto', 'danado') else False,
                'block_expiration_date': self.expiration_date,
            }

            if not location.original_parent_id:
                vals['original_parent_id'] = location.location_id.id

            location.with_context(skip_history_write=True).sudo().write(vals)

            # Create history entry
            self.env['stock.location.block.history'].create({
                'location_id': location.id,
                'event_type': 'block',
                'block_reason_type': self.block_reason_type,
                'block_reason': vals['block_reason'],
                'date': vals['block_date'],
                'user_id': vals['block_user_id'],
                'ticket': vals['block_ticket'],
                'comment': self.comment
            })

        return {'type': 'ir.actions.act_window_close'}
