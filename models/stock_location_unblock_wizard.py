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

class StockLocationMassUnblockWizard(models.TransientModel):
    _name = 'wb.stock.location.mass.unblock.wizard'
    _description = 'Asistente para Desbloqueo Masivo'

    location_ids = fields.Many2many('stock.location', string='Ubicaciones a Desbloquear', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids')
        if active_model == 'stock.location' and active_ids:
            res['location_ids'] = [(6, 0, active_ids)]
        return res

    def action_confirm_unblock(self):
        self.ensure_one()
        self.location_ids.action_mass_unblock()
        return {'type': 'ir.actions.act_window_close'}
