# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def write(self, vals):
        res = super(PurchaseOrder, self).write(vals)
        if 'check_commertial' in vals and vals.get('check_commertial'):
            # Vo.Bo is granted, search and unblock any locations blocked for this PO
            for po in self:
                # Find blocked locations under Cuarentena for this PO
                blocked_locations = self.env['stock.location'].search([
                    ('block_reason_type', '=', 'cuarentena'),
                    ('original_parent_id', '!=', False),
                    ('block_reason', 'like', f"PO: {po.name}")
                ])
                if blocked_locations:
                    _logger.info("Desbloqueando automáticamente ubicaciones para PO %s debido a Vo.Bo. COMEX: %s", po.name, blocked_locations.mapped('name'))
                    for loc in blocked_locations:
                        # Write directly to update parent location and original_parent_id
                        # which triggers history creation and resets block fields automatically
                        loc.sudo().write({
                            'location_id': loc.original_parent_id.id,
                            'original_parent_id': False,
                        })
        return res
