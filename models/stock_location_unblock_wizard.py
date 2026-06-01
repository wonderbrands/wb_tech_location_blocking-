# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError

class StockLocationUnblockWizard(models.TransientModel):
    _name = 'wb.stock.location.unblock.wizard'
    _description = 'Confirmar Desbloqueo de Ubicación'

    location_id = fields.Many2one('stock.location', string='Ubicación', required=True)
    is_repaired = fields.Boolean(string='¿La reparación está concluida?', required=True, default=False)
    comment = fields.Text(string='Comentario')

    def action_confirm_unblock(self):
        self.ensure_one()
        if not self.is_repaired:
            raise UserError("Debe confirmar que la reparación está concluida para poder desbloquear la ubicación.")
            
        self.location_id._do_unblock(comment=self.comment or 'Desbloqueo tras conclusión de reparación.')
        return {'type': 'ir.actions.act_window_close'}
