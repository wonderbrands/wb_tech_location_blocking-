# -*- coding: utf-8 -*-
from odoo import models, fields

class UserRole(models.Model):
    _inherit = 'user.role'

    parent_role_id = fields.Many2one('user.role')
    date_from = fields.Date()
    date_to = fields.Date()
    fallback_role_id = fields.Many2one('user.role')
    is_expired = fields.Boolean()

    def create_role_template(self):
        return True

    def action_compare_role(self):
        return True

    def action_copy_to_company(self):
        return True

    def action_export_user_role(self):
        return True

class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    def _validate_view(self, arch, model, platform=False):
        return True
