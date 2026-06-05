# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError

class CycleCountSelectedLocation(models.Model):
    _inherit = "cycle.count.selected.location"

    @api.constrains('location_id')
    def _check_not_blocked(self):
        for rec in self:
            if rec.location_id and rec.location_id.is_location_blocked():
                cc_name = rec.cycle_count_id.name
                if cc_name and rec.location_id.block_reason and f"Conteo Cíclico: {cc_name}" in rec.location_id.block_reason:
                    continue
                raise UserError(f"La ubicación {rec.location_id.complete_name} está bloqueada y no se puede incluir en un conteo cíclico.")

class CycleCountLine(models.Model):
    _inherit = "cycle.count.line"

    @api.constrains('stock_location_id')
    def _check_not_blocked(self):
        for rec in self:
            if rec.stock_location_id and rec.stock_location_id.is_location_blocked():
                cc_name = rec.wave_id.cycle_count_id.name
                if cc_name and rec.stock_location_id.block_reason and f"Conteo Cíclico: {cc_name}" in rec.stock_location_id.block_reason:
                    continue
                raise UserError(f"La ubicación {rec.stock_location_id.complete_name} está bloqueada y no se puede incluir en un conteo cíclico.")

