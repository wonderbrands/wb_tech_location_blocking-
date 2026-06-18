# -*- coding: utf-8 -*-
from odoo import models, fields, api

class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def write(self, vals):
        locations_to_check = self.mapped('location_id')
        res = super(StockQuant, self).write(vals)
        if 'quantity' in vals or 'location_id' in vals:
            locations_to_check._check_and_unblock_oversized()
        return res

    def unlink(self):
        locations_to_check = self.mapped('location_id')
        res = super(StockQuant, self).unlink()
        locations_to_check._check_and_unblock_oversized()
        return res
