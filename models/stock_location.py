# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError

class StockLocation(models.Model):
    _inherit = 'stock.location'

    block_reason_type = fields.Selection([
        ('ciclico', 'Cíclico'),
        ('no_apto', 'No Apta'),
        ('sobredimensionada', 'Sobredimensionada'),
        ('cuarentena', 'Cuarentena')
    ], string='Tipo de Bloqueo', copy=False)
    
    block_reason = fields.Char(string='Motivo de Bloqueo', db_column='block_reason_text', copy=False)
    original_parent_id = fields.Many2one('stock.location', string='Ubicación padre original', copy=False)
    
    # Stored computed field to support reporting: if blocked, returns the original parent location, otherwise returns the current parent location
    reporting_parent_id = fields.Many2one(
        'stock.location', 
        string='Ubicación Padre (Reportes)', 
        compute='_compute_reporting_parent_id', 
        store=True,
        copy=False
    )
    
    block_date = fields.Datetime(string='Fecha/Hora de Bloqueo', copy=False)
    block_user_id = fields.Many2one('res.users', string='Usuario que Bloqueó', copy=False)
    block_ticket = fields.Char(string='Ticket de Mantenimiento', copy=False)
    block_expiration_date = fields.Date(string='Fecha de Expiración de Bloqueo', copy=False)
    is_block_expired = fields.Boolean(string='Bloqueo Expirado', compute='_compute_is_block_expired')

    @api.depends('block_expiration_date')
    def _compute_is_block_expired(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.block_expiration_date and rec.block_expiration_date < today:
                rec.is_block_expired = True
            else:
                rec.is_block_expired = False
    
    block_history_ids = fields.One2many(
        'stock.location.block.history', 
        'location_id', 
        string='Historial de Bloqueos'
    )
    
    # Antigüedad en días (para reportería)
    block_age_days = fields.Integer(
        string='Antigüedad (Días)', 
        compute='_compute_block_age_days', 
        store=True
    )

    @api.depends('block_date')
    def _compute_block_age_days(self):
        now = fields.Datetime.now()
        for rec in self:
            if rec.block_date:
                delta = now - rec.block_date
                rec.block_age_days = delta.days
            else:
                rec.block_age_days = 0

    @api.depends('location_id', 'original_parent_id')
    def _compute_reporting_parent_id(self):
        for rec in self:
            if rec.original_parent_id:
                rec.reporting_parent_id = rec.original_parent_id
            else:
                rec.reporting_parent_id = rec.location_id

    def action_open_block_wizard(self):
        self.ensure_one()
        return {
            'name': 'Bloquear Ubicación',
            'type': 'ir.actions.act_window',
            'res_model': 'wb.stock.location.block.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'stock.location',
                'active_ids': [self.id],
                'default_location_id': self.id,
            }
        }

    def action_unblock(self):
        self.ensure_one()
        if not self.original_parent_id:
            return {'type': 'ir.actions.client', 'tag': 'reload'}

        is_quarantine = (
            self.block_reason_type == 'cuarentena' or
            (self.block_reason and 'cuarentena' in self.block_reason.lower()) or
            (self.location_id and 'cuarentena' in (self.location_id.complete_name or '').lower())
        )
        if is_quarantine:
            raise UserError("No se permite desbloquear manualmente una ubicación en cuarentena.")

        if self.block_reason_type == 'no_apto':
            if not self.env.user.has_group('wb_tech_location_blocking.group_lider_de_turno'):
                raise UserError("Solo el Líder de turno puede desbloquear una ubicación No Apta.")
            return {
                'name': 'Confirmar Desbloqueo',
                'type': 'ir.actions.act_window',
                'res_model': 'wb.stock.location.unblock.wizard',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'default_location_id': self.id,
                }
            }

        elif self.block_reason_type == 'ciclico':
            if not self.env.user.has_group('stock.group_stock_user'):
                raise UserError("Solo un Operador de inventario puede desbloquear esta ubicación.")

        self._do_unblock()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _do_unblock(self, comment=None):
        self.ensure_one()
        is_quarantine = (
            self.block_reason_type == 'cuarentena' or
            (self.block_reason and 'cuarentena' in self.block_reason.lower()) or
            (self.location_id and 'cuarentena' in (self.location_id.complete_name or '').lower())
        )
        if is_quarantine:
            raise UserError("No se permite desbloquear una ubicación en cuarentena.")
            
        # Save to history before unblocking
        self.env['stock.location.block.history'].create({
            'location_id': self.id,
            'event_type': 'unblock',
            'block_reason_type': self.block_reason_type,
            'block_reason': self.block_reason,
            'date': fields.Datetime.now(),
            'user_id': self.env.user.id,
            'ticket': self.block_ticket,
            'comment': comment or 'Desbloqueo completado.'
        })
        
        # Restore parent and clear fields
        vals = {
            'block_reason_type': False,
            'block_reason': False,
            'block_date': False,
            'block_user_id': False,
            'block_ticket': False,
            'block_expiration_date': False,
        }
        if self.original_parent_id:
            vals['location_id'] = self.original_parent_id.id
            vals['original_parent_id'] = False
            
        self.sudo().write(vals)
        return True
