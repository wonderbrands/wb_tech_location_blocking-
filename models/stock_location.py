# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockLocation(models.Model):
    _inherit = 'stock.location'

    block_reason_type = fields.Selection([
        ('ciclico', 'Cíclico'),
        ('no_apto', 'No Apta'),
        ('sobredimensionada', 'Sobredimensionada'),
        ('cuarentena', 'Cuarentena'),
        ('danado', 'Dañada'),
        ('onsite', 'Onsite')
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
    
    oversized_from_location_id = fields.Many2one('stock.location', string='Sobredimensionada Desde', copy=False)
    oversized_location_ids = fields.One2many(
        'stock.location', 
        'oversized_from_location_id', 
        string='Ubicaciones Sobredimensionadas'
    )
    
    loc_pasillo = fields.Char(string='Pasillo', compute='_compute_nomenclature_fields', store=True, copy=False)
    loc_posicion = fields.Char(string='Posición', compute='_compute_nomenclature_fields', store=True, copy=False)
    loc_frente = fields.Char(string='Frente', compute='_compute_nomenclature_fields', store=True, copy=False)
    loc_nivel = fields.Char(string='Nivel', compute='_compute_nomenclature_fields', store=True, copy=False)

    block_date = fields.Datetime(string='Fecha/Hora de Bloqueo', copy=False)
    block_user_id = fields.Many2one('res.users', string='Usuario que Bloqueó', copy=False)
    block_ticket = fields.Char(string='Ticket de Mantenimiento', copy=False)
    block_expiration_date = fields.Date(string='Fecha de Expiración de Bloqueo', copy=False)
    is_block_expired = fields.Boolean(string='Bloqueo Expirado', compute='_compute_is_block_expired')
    is_empty_location = fields.Boolean(
        string='Ubicación Vacía', 
        compute='_compute_is_empty_location', 
        search='_search_is_empty_location'
    )

    @api.depends('block_expiration_date')
    def _compute_is_block_expired(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.block_expiration_date and rec.block_expiration_date < today:
                rec.is_block_expired = True
            else:
                rec.is_block_expired = False

    def _compute_is_empty_location(self):
        for rec in self:
            quants = self.env['stock.quant'].sudo().search([
                ('location_id', '=', rec.id),
                ('quantity', '>', 0)
            ], limit=1)
            rec.is_empty_location = not bool(quants)

    def _search_is_empty_location(self, operator, value):
        if operator not in ('=', '!='):
            raise UserError("Operación no soportada para buscar ubicación vacía.")
        self.env['stock.quant'].flush_model(['location_id', 'quantity'])
        query = """
            SELECT DISTINCT location_id 
            FROM stock_quant 
            WHERE quantity > 0
        """
        self.env.cr.execute(query)
        res = self.env.cr.fetchall()
        location_with_stock_ids = [r[0] for r in res if r[0]]
        
        target_value = value if operator == '=' else not value
        if target_value:
            return [('id', 'not in', location_with_stock_ids)]
        else:
            return [('id', 'in', location_with_stock_ids)]
    
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

    def action_generate_blocked_report_csv(self):
        url = '/web/blocked_locations_csv'
        if self:
            wizard = self.env['wb.stock.location.blocked.report.wizard'].create({
                'location_ids': [(6, 0, self.ids)]
            })
            url += f'?wizard_id={wizard.id}'
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }


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

    def action_open_oversized_wizard(self):
        self.ensure_one()
        return {
            'name': 'Sobredimensionar Ubicación',
            'type': 'ir.actions.act_window',
            'res_model': 'wb.stock.location.oversized.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'stock.location',
                'active_id': self.id,
                'default_original_location_id': self.id,
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

        if self.block_reason_type in ('no_apto', 'danado', 'onsite'):
            if not self.env.user.has_group('wb_tech_location_blocking.group_lider_de_turno'):
                liders = self.env.ref('wb_tech_location_blocking.group_lider_de_turno').users.mapped('name')
                raise UserError(f"Solo el Líder de turno puede realizar esta acción. Solicita a alguno de los siguientes usuarios que desbloqueen esta ubicación: {', '.join(liders)}")
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
            raise UserError("No se permite desbloquear manualmente una ubicación en conteo cíclico. Debe salir del conteo cíclico de WMDS.")

        elif self.block_reason_type == 'sobredimensionada':
            if not self.env.user.has_group('stock.group_stock_user'):
                raise UserError("Solo un Operador de inventario puede desbloquear esta ubicación.")

        self._do_unblock()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _do_unblock(self, comment=None):
        self.ensure_one()
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
            'oversized_from_location_id': False,
        }
        if self.original_parent_id:
            vals['location_id'] = self.original_parent_id.id
            vals['original_parent_id'] = False
            
        self.with_context(skip_history_write=True).sudo().write(vals)
        return True

    @api.depends('name')
    def _compute_nomenclature_fields(self):
        for rec in self:
            parts = (rec.name or '').split('-')
            if len(parts) == 4:
                rec.loc_pasillo = parts[0]
                rec.loc_posicion = parts[1]
                rec.loc_frente = parts[2]
                rec.loc_nivel = parts[3]
            else:
                rec.loc_pasillo = False
                rec.loc_posicion = False
                rec.loc_frente = False
                rec.loc_nivel = False

    @api.model_create_multi
    def create(self, vals_list):
        wmds_blocked = self.env.ref('wmds.location_blocked', raise_if_not_found=False)
        ciclico_dest = self.env.ref('wb_tech_location_blocking.location_blocked_ciclico', raise_if_not_found=False)
        no_apto_dest = self.env.ref('wb_tech_location_blocking.location_blocked_no_apto', raise_if_not_found=False)
        sobredim_dest = self.env.ref('wb_tech_location_blocking.location_blocked_sobredimensionada', raise_if_not_found=False)
        cuarentena_dest = self.env['stock.location'].search([('complete_name', '=', 'WH/Cuarentena')], limit=1)
        if not cuarentena_dest:
            cuarentena_dest = self.env['stock.location'].search([
                ('name', '=', 'Cuarentena'),
                ('location_id.name', '=', 'WH')
            ], limit=1)
        danado_dest = self.env.ref('wb_tech_location_blocking.location_blocked_danado', raise_if_not_found=False)
        onsite_dest = self.env.ref('wb_tech_location_blocking.location_blocked_onsite', raise_if_not_found=False)
        
        blocked_ids = {
            wmds_blocked.id if wmds_blocked else False,
            ciclico_dest.id if ciclico_dest else False,
            no_apto_dest.id if no_apto_dest else False,
            sobredim_dest.id if sobredim_dest else False,
            cuarentena_dest.id if cuarentena_dest else False,
            danado_dest.id if danado_dest else False,
            onsite_dest.id if onsite_dest else False,
        } - {False}

        for vals in vals_list:
            if wmds_blocked and vals.get('location_id') == wmds_blocked.id:
                is_virtual = vals.get('name') in ['Ciclico', 'NoApta', 'Sobredimensionada', 'Cuarentena', 'Dañada', 'Onsite']
                if not is_virtual:
                    reason_type = vals.get('block_reason_type')
                    reason_text = (vals.get('block_reason') or '').lower()
                    
                    if not reason_type:
                        if any(x in reason_text for x in ['dañado', 'danado', 'dañada', 'daña']):
                            reason_type = 'danado'
                        elif any(x in reason_text for x in ['onsite', 'on-site']):
                            reason_type = 'onsite'
                        elif any(x in reason_text for x in ['no apto', 'no_apto', 'mantenimiento', 'incidencia', 'daño', 'daño estructural']):
                            reason_type = 'no_apto'
                        else:
                            reason_type = 'ciclico'
                    
                    if reason_type == 'ciclico':
                        if ciclico_dest:
                            vals['location_id'] = ciclico_dest.id
                            vals['block_reason_type'] = 'ciclico'
                    elif reason_type == 'no_apto':
                        if no_apto_dest:
                            vals['location_id'] = no_apto_dest.id
                            vals['block_reason_type'] = 'no_apto'
                    elif reason_type == 'danado':
                        if danado_dest:
                            vals['location_id'] = danado_dest.id
                            vals['block_reason_type'] = 'danado'
                    elif reason_type == 'onsite':
                        if onsite_dest:
                            vals['location_id'] = onsite_dest.id
                            vals['block_reason_type'] = 'onsite'

            if vals.get('location_id') in blocked_ids:
                if not vals.get('block_date'):
                    vals['block_date'] = fields.Datetime.now()
                if not vals.get('block_user_id'):
                    vals['block_user_id'] = self.env.user.id

            if 'original_parent_id' in vals and not vals.get('original_parent_id'):
                vals.update({
                    'block_reason_type': False,
                    'block_reason': False,
                    'block_date': False,
                    'block_user_id': False,
                    'block_ticket': False,
                    'block_expiration_date': False,
                    'oversized_from_location_id': False,
                })
        
        res = super(StockLocation, self).create(vals_list)

        # Create history for created locations that are blocked
        if not self.env.context.get('skip_history_write'):
            history_to_create = []
            for rec in res:
                if rec.original_parent_id or rec.location_id.id in blocked_ids:
                    r_type = rec.block_reason_type or 'ciclico'
                    history_to_create.append({
                        'location_id': rec.id,
                        'event_type': 'block',
                        'block_reason_type': r_type,
                        'block_reason': rec.block_reason or f"Bloqueado/{r_type}",
                        'date': rec.block_date or fields.Datetime.now(),
                        'user_id': rec.block_user_id.id or self.env.user.id,
                        'ticket': rec.block_ticket,
                        'comment': rec.block_reason or 'Bloqueo automático/API en creación.'
                    })
            if history_to_create:
                self.env['stock.location.block.history'].create(history_to_create)

        return res

    def write(self, vals):
        wmds_blocked = self.env.ref('wmds.location_blocked', raise_if_not_found=False)
        ciclico_dest = self.env.ref('wb_tech_location_blocking.location_blocked_ciclico', raise_if_not_found=False)
        no_apto_dest = self.env.ref('wb_tech_location_blocking.location_blocked_no_apto', raise_if_not_found=False)
        sobredim_dest = self.env.ref('wb_tech_location_blocking.location_blocked_sobredimensionada', raise_if_not_found=False)
        cuarentena_dest = self.env['stock.location'].search([('complete_name', '=', 'WH/Cuarentena')], limit=1)
        if not cuarentena_dest:
            cuarentena_dest = self.env['stock.location'].search([
                ('name', '=', 'Cuarentena'),
                ('location_id.name', '=', 'WH')
            ], limit=1)
        danado_dest = self.env.ref('wb_tech_location_blocking.location_blocked_danado', raise_if_not_found=False)
        onsite_dest = self.env.ref('wb_tech_location_blocking.location_blocked_onsite', raise_if_not_found=False)
        
        blocked_ids = {
            wmds_blocked.id if wmds_blocked else False,
            ciclico_dest.id if ciclico_dest else False,
            no_apto_dest.id if no_apto_dest else False,
            sobredim_dest.id if sobredim_dest else False,
            cuarentena_dest.id if cuarentena_dest else False,
            danado_dest.id if danado_dest else False,
            onsite_dest.id if onsite_dest else False,
        } - {False}

        # 1. Intercept blocking writes to wmds.location_blocked and redirect them
        is_virtual_subloc = False
        if wmds_blocked:
            virtual_subloc_ids = {
                ciclico_dest.id if ciclico_dest else False,
                no_apto_dest.id if no_apto_dest else False,
                sobredim_dest.id if sobredim_dest else False,
                cuarentena_dest.id if cuarentena_dest else False,
                danado_dest.id if danado_dest else False,
                onsite_dest.id if onsite_dest else False,
                wmds_blocked.id,
            } - {False}
            if any(rec.id in virtual_subloc_ids for rec in self):
                is_virtual_subloc = True

        if not is_virtual_subloc and wmds_blocked and vals.get('location_id') == wmds_blocked.id:
            reason_type = vals.get('block_reason_type')
            reason_text = (vals.get('block_reason') or '').lower()
            
            if not reason_type:
                if any(x in reason_text for x in ['dañado', 'danado', 'dañada', 'daña']):
                    reason_type = 'danado'
                elif any(x in reason_text for x in ['onsite', 'on-site']):
                    reason_type = 'onsite'
                elif any(x in reason_text for x in ['no apto', 'no_apto', 'mantenimiento', 'incidencia', 'daño', 'daño estructural']):
                    reason_type = 'no_apto'
                elif any(x in reason_text for x in ['cuarentena']):
                    reason_type = 'cuarentena'
                else:
                    reason_type = 'ciclico'
            
            # Map to the new sub-locations
            if reason_type == 'ciclico':
                if ciclico_dest:
                    vals['location_id'] = ciclico_dest.id
                    vals['block_reason_type'] = 'ciclico'
            elif reason_type == 'no_apto':
                if no_apto_dest:
                    vals['location_id'] = no_apto_dest.id
                    vals['block_reason_type'] = 'no_apto'
            elif reason_type == 'danado':
                if danado_dest:
                    vals['location_id'] = danado_dest.id
                    vals['block_reason_type'] = 'danado'
            elif reason_type == 'onsite':
                if onsite_dest:
                    vals['location_id'] = onsite_dest.id
                    vals['block_reason_type'] = 'onsite'
            elif reason_type == 'cuarentena':
                if cuarentena_dest:
                    vals['location_id'] = cuarentena_dest.id
                    vals['block_reason_type'] = 'cuarentena'

        # Determine reason_type if blocking
        reason_type = False
        if vals.get('location_id') in blocked_ids:
            reason_type = vals.get('block_reason_type')
            if not reason_type:
                loc_id = vals.get('location_id')
                if ciclico_dest and loc_id == ciclico_dest.id:
                    reason_type = 'ciclico'
                elif no_apto_dest and loc_id == no_apto_dest.id:
                    reason_type = 'no_apto'
                elif danado_dest and loc_id == danado_dest.id:
                    reason_type = 'danado'
                elif onsite_dest and loc_id == onsite_dest.id:
                    reason_type = 'onsite'
                elif sobredim_dest and loc_id == sobredim_dest.id:
                    reason_type = 'sobredimensionada'
                elif cuarentena_dest and loc_id == cuarentena_dest.id:
                    reason_type = 'cuarentena'
            
            # Ensure block_date and block_user_id are filled if not provided
            if not vals.get('block_date'):
                vals['block_date'] = fields.Datetime.now()
            if not vals.get('block_user_id'):
                vals['block_user_id'] = self.env.user.id

        # 2. Intercept unblocking writes (e.g. from wmds) and clean up metadata
        if 'original_parent_id' in vals and not vals.get('original_parent_id'):
            vals.update({
                'block_reason_type': False,
                'block_reason': False,
                'block_date': False,
                'block_user_id': False,
                'block_ticket': False,
                'block_expiration_date': False,
                'oversized_from_location_id': False,
            })

        # 3. Detect changes to create history
        history_to_create = []
        if not self.env.context.get('skip_history_write'):
            for rec in self:
                is_blocking = vals.get('location_id') in blocked_ids and not rec.original_parent_id
                if is_blocking:
                    r_type = reason_type or vals.get('block_reason_type') or 'ciclico'
                    history_to_create.append({
                        'location_id': rec.id,
                        'event_type': 'block',
                        'block_reason_type': r_type,
                        'block_reason': vals.get('block_reason') or f"Bloqueado/{r_type}",
                        'date': vals.get('block_date') or fields.Datetime.now(),
                        'user_id': vals.get('block_user_id') or self.env.user.id,
                        'ticket': vals.get('block_ticket'),
                        'comment': vals.get('block_reason') or 'Bloqueo automático/API.'
                    })
                is_unblocking = 'original_parent_id' in vals and not vals.get('original_parent_id') and rec.original_parent_id
                if is_unblocking:
                    history_to_create.append({
                        'location_id': rec.id,
                        'event_type': 'unblock',
                        'block_reason_type': rec.block_reason_type,
                        'block_reason': rec.block_reason,
                        'date': fields.Datetime.now(),
                        'user_id': self.env.user.id,
                        'ticket': rec.block_ticket,
                        'comment': 'Desbloqueo automático/API.'
                    })

        res = super(StockLocation, self).write(vals)

        # Create history after write
        if history_to_create:
            self.env['stock.location.block.history'].create(history_to_create)

        return res

    def init(self):
        super().init()
        # Find WH location (which has parent_id = False, and name = 'WH')
        wh = self.env['stock.location'].search([('name', '=', 'WH'), ('location_id', '=', False)], limit=1)
        if not wh:
            # Fallback to stock location parent
            stock_loc = self.env.ref('stock.stock_location_stock', raise_if_not_found=False)
            if stock_loc:
                wh = stock_loc.location_id

        if wh:
            # Set parent of Bloqueado to WH
            wmds_blocked = self.env.ref('wmds.location_blocked', raise_if_not_found=False)
            if wmds_blocked and wmds_blocked.location_id != wh:
                wmds_blocked.write({'location_id': wh.id})
                _logger.info("Set parent of wmds.location_blocked to WH")

            # Clean up old WH/Bloqueado/Cuarentena and migrate existing data to WH/Cuarentena
            old_cuarentena = self.env['stock.location'].search([('complete_name', '=', 'WH/Bloqueado/Cuarentena')], limit=1)
            new_cuarentena = self.env['stock.location'].search([('complete_name', '=', 'WH/Cuarentena')], limit=1)
            if not new_cuarentena:
                new_cuarentena = self.env['stock.location'].search([('name', '=', 'Cuarentena'), ('location_id', '=', wh.id)], limit=1)

            if not new_cuarentena:
                new_cuarentena = self.env['stock.location'].create({
                    'name': 'Cuarentena',
                    'location_id': wh.id,
                    'usage': 'internal'
                })
                _logger.info("Created standard WH/Cuarentena location")

            if old_cuarentena and new_cuarentena:
                # Move child locations
                locations_to_move = self.env['stock.location'].search([('location_id', '=', old_cuarentena.id)])
                for loc in locations_to_move:
                    loc.sudo().write({'location_id': new_cuarentena.id})
                    _logger.info("Migrated blocked location %s parent to %s", loc.name, new_cuarentena.complete_name)
                
                # Move quants
                self.env['stock.quant'].search([('location_id', '=', old_cuarentena.id)]).sudo().write({'location_id': new_cuarentena.id})

                # Delete ir.model.data if exists
                xml_id_rec = self.env['ir.model.data'].search([
                    ('module', '=', 'wb_tech_location_blocking'),
                    ('name', '=', 'location_blocked_cuarentena')
                ])
                if xml_id_rec:
                    xml_id_rec.unlink()

                # Delete old location
                old_cuarentena.sudo().unlink()
                _logger.info("Successfully deleted old WH/Bloqueado/Cuarentena location and migrated references.")

    def action_mass_unblock(self):
        blocked_records = self.filtered(lambda r: r.original_parent_id)
        if not blocked_records:
            return True

        # Check permissions: if any is blocked as no_apto, danado, or onsite
        requires_lider = blocked_records.filtered(
            lambda r: r.block_reason_type in ('no_apto', 'danado', 'onsite')
        )
        if requires_lider and not self.env.user.has_group('wb_tech_location_blocking.group_lider_de_turno'):
            liders = self.env.ref('wb_tech_location_blocking.group_lider_de_turno').users.mapped('name')
            raise UserError(f"Solo el Líder de turno puede realizar esta acción. Solicita a alguno de los siguientes usuarios que desbloqueen estas ubicaciones: {', '.join(liders)}")

        # Check cyclic or quarantine
        for rec in blocked_records:
            if rec.block_reason_type == 'ciclico':
                raise UserError(f"La ubicación {rec.complete_name} está en conteo cíclico y no se puede desbloquear manualmente.")
            is_quarantine = (
                rec.block_reason_type == 'cuarentena' or
                (rec.block_reason and 'cuarentena' in rec.block_reason.lower()) or
                (rec.location_id and 'cuarentena' in (rec.location_id.complete_name or '').lower())
            )
            if is_quarantine:
                raise UserError(f"La ubicación {rec.complete_name} está en cuarentena y no se puede desbloquear manualmente.")

        for rec in blocked_records:
            rec._do_unblock(comment="Desbloqueo masivo.")

        return True

    def is_location_blocked(self):
        """Returns True if the location is blocked (has a block reason or is nested under a blocked parent location)."""
        self.ensure_one()
        is_blocked = (
            self.original_parent_id or
            self.block_reason_type or
            (self.location_id and 'bloqueado' in (self.location_id.complete_name or '').lower()) or
            (self.location_id and 'cuarentena' in (self.location_id.complete_name or '').lower()) or
            'bloqueado' in (self.complete_name or '').lower() or
            'cuarentena' in (self.complete_name or '').lower()
        )
        return bool(is_blocked)


class StockLocationBlockedReportWizard(models.TransientModel):
    _name = 'wb.stock.location.blocked.report.wizard'
    _description = 'Wizard de Reporte de Posiciones Bloqueadas'

    location_ids = fields.Many2many('stock.location', string='Ubicaciones')

