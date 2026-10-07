# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    @api.model
    def _is_blocked_location(self, location):
        """Return True if the location is (or is nested under) a blocked location.

        A location is considered blocked when:
        - it keeps an original_parent_id (i.e. it was reparented because blocked), or
        - any of its ancestors is part of the WH/Bloqueado or WH/Cuarentena subtree, or
        - its complete name mentions 'bloquead'/'cuarentena'.
        """
        if not location:
            return False
        if location.original_parent_id:
            return True
        if location.block_reason_type:
            return True
        # Walk up the parent chain, checking for a blocked container ancestor.
        current = location
        seen = set()
        while current and current.id and current.id not in seen:
            seen.add(current.id)
            name = (current.complete_name or '').lower()
            if 'bloquead' in name or 'bloqueo' in name or 'cuarentena' in name:
                return True
            if current.original_parent_id:
                return True
            current = current.location_id
        return False

    @api.model
    def _check_move_line_locations_blocked(self, location_id, location_dest_id):
        if self.env.context.get('skip_blocking_check'):
            return
        if location_id:
            loc = self.env['stock.location'].browse(location_id)
            if self._is_blocked_location(loc):
                raise UserError(
                    "La ubicación de origen %s está bloqueada y no se permite ningún movimiento desde ella."
                    % (loc.complete_name or loc.name)
                )
        if location_dest_id:
            loc = self.env['stock.location'].browse(location_dest_id)
            if self._is_blocked_location(loc):
                raise UserError(
                    "La ubicación de destino %s está bloqueada y no se permite ningún movimiento hacia ella."
                    % (loc.complete_name or loc.name)
                )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._check_move_line_locations_blocked(
                vals.get('location_id'),
                vals.get('location_dest_id'),
            )
        return super(StockMoveLine, self).create(vals_list)

    def write(self, vals):
        if 'location_id' in vals or 'location_dest_id' in vals:
            for rec in self:
                new_location_id = vals.get('location_id', rec.location_id.id)
                new_location_dest_id = vals.get('location_dest_id', rec.location_dest_id.id)
                self._check_move_line_locations_blocked(new_location_id, new_location_dest_id)
        else:
            # Even without changing locations, a line already sitting on a blocked
            # source or destination must not be modified (other than quantity
            # adjustments that opt-in through 'skip_blocking_check').
            if not self.env.context.get('skip_blocking_check'):
                for rec in self:
                    if self._is_blocked_location(rec.location_id) or self._is_blocked_location(rec.location_dest_id):
                        blocked = rec.location_id if self._is_blocked_location(rec.location_id) else rec.location_dest_id
                        raise UserError(
                            "La línea de movimiento usa la ubicación bloqueada %s y no se puede modificar."
                            % (blocked.complete_name or blocked.name)
                        )
        return super(StockMoveLine, self).write(vals)
