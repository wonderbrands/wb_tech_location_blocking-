# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    location_id = fields.Many2one(
        'stock.location',
        domain="[('usage', '!=', 'view'), ('complete_name', 'not ilike', 'Bloqueado')]"
    )
    location_dest_id = fields.Many2one(
        'stock.location',
        domain="[('usage', '!=', 'view'), ('complete_name', 'not ilike', 'Bloqueado')]"
    )

    def button_validate(self):
        # Run super first to validate the picking
        res = super(StockPicking, self).button_validate()

        for picking in self:
            if picking.picking_type_id.name in ('Rackeo', 'Rackeos'):
                clean_origin = picking.origin.replace('COMEX: ', '') if picking.origin else ''
                po = self.env['purchase.order'].search(
                    [('name', '=', clean_origin)],
                    limit=1
                )
                if po and not po.check_commertial:
                    # Find the destination locations of the moves with quantity > 0
                    active_moves = picking.move_ids.filtered(
                        lambda m: getattr(m, 'quantity', getattr(m, 'quantity_done', 0.0)) > 0
                    )
                    dest_locations = active_moves.mapped('location_dest_id')
                    cuarentena_parent = self.env['stock.location'].sudo().search([('complete_name', '=', 'WH/Cuarentena')], limit=1)
                    if not cuarentena_parent:
                        cuarentena_parent = self.env['stock.location'].sudo().search([
                            ('name', '=', 'Cuarentena'),
                            ('location_id.name', '=', 'WH')
                        ], limit=1)
                    
                    if not cuarentena_parent:
                        _logger.warning("Cuarentena parent location not found. Cannot block locations.")
                        continue

                    for loc in dest_locations:
                        if loc.usage == 'internal' and not loc.original_parent_id:
                            # Block the location
                            loc.sudo().write({
                                'location_id': cuarentena_parent.id,
                                'block_reason_type': 'cuarentena',
                                'block_reason': f"Bloqueo automático COMEX por falta de Vo.Bo. (PO: {po.name})",
                                'original_parent_id': loc.location_id.id,
                            })
                            
                            # Create block history
                            self.env['stock.location.block.history'].create({
                                'location_id': loc.id,
                                'event_type': 'block',
                                'block_reason_type': 'cuarentena',
                                'block_reason': f"Bloqueo automático COMEX por falta de Vo.Bo. (PO: {po.name})",
                                'date': fields.Datetime.now(),
                                'user_id': self.env.user.id,
                                'comment': f"Bloqueo automático de ubicación tras validación de rackeo (PO: {po.name})."
                            })
        return res
