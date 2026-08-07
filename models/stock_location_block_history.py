# -*- coding: utf-8 -*-
from odoo import models, fields

class StockLocationBlockHistory(models.Model):
    _name = 'stock.location.block.history'
    _description = 'Historial de Bloqueo de Ubicación'
    _order = 'date desc'

    location_id = fields.Many2one('stock.location', string='Ubicación', required=True, ondelete='cascade')
    event_type = fields.Selection([
        ('block', 'Bloqueo'),
        ('unblock', 'Desbloqueo')
    ], string='Evento', required=True)
    
    block_reason_type = fields.Selection([
        ('ciclico', 'Cíclico'),
        ('no_apto', 'No Apta'),
        ('sobredimensionada', 'Sobredimensionada'),
        ('cuarentena', 'Cuarentena'),
        ('danado', 'Dañada'),
        ('onsite', 'Onsite'),
        ('dupla', 'Dupla'),
        ('materiales', 'Materiales')
    ], string='Tipo de Bloqueo')
    
    block_reason = fields.Char(string='Motivo/Comentario original')
    date = fields.Datetime(string='Fecha/Hora', default=fields.Datetime.now, required=True)
    user_id = fields.Many2one('res.users', string='Usuario', required=True)
    ticket = fields.Char(string='Ticket de Mantenimiento')
    comment = fields.Text(string='Comentarios')
