# -*- coding: utf-8 -*-
import csv
import io
from datetime import datetime
from odoo import http
from odoo.http import request, content_disposition

class BlockedLocationsReportController(http.Controller):

    @http.route('/web/blocked_locations_csv', type='http', auth='user')
    def download_blocked_locations_csv(self, wizard_id=None, ids=None, **kwargs):
        # Determine which locations to export
        domain = [('original_parent_id', '!=', False)]
        if wizard_id:
            try:
                wizard = request.env['wb.stock.location.blocked.report.wizard'].sudo().browse(int(wizard_id))
                if wizard.exists() and wizard.location_ids:
                    domain.append(('id', 'in', wizard.location_ids.ids))
            except ValueError:
                pass
        elif ids:
            try:
                id_list = [int(x) for x in ids.split(',') if x.strip()]
                if id_list:
                    domain.append(('id', 'in', id_list))
            except ValueError:
                pass
        
        locations = request.env['stock.location'].sudo().search(domain)

        # Create string buffer for CSV in-memory
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',', quotechar='"', quoting=csv.QUOTE_MINIMAL)

        # Write header
        writer.writerow([
            'Posición Completa',
            'Bloqueado',
            'Padre Original',
            'Sobredimensionado Desde',
            'Motivo',
            'Persona',
            'Timestamp',
            'Expiración',
            '¿Ya está expirado?',
            'Pasillo',
            'Posición',
            'Frente',
            'Nivel'
        ])

        # Write rows
        for loc in locations:
            # Parse nomenclature dynamically if stored fields are empty
            parts = (loc.name or '').split('-')
            pasillo = loc.loc_pasillo or (parts[0] if len(parts) == 4 else '')
            posicion = loc.loc_posicion or (parts[1] if len(parts) == 4 else '')
            frente = loc.loc_frente or (parts[2] if len(parts) == 4 else '')
            nivel = loc.loc_nivel or (parts[3] if len(parts) == 4 else '')

            # Format datetime safely
            block_date_str = ''
            if loc.block_date:
                user_tz = request.env.user.tz or 'UTC'
                try:
                    import pytz
                    utc_dt = pytz.utc.localize(loc.block_date)
                    local_dt = utc_dt.astimezone(pytz.timezone(user_tz))
                    block_date_str = local_dt.strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    block_date_str = loc.block_date.strftime('%Y-%m-%d %H:%M:%S')

            block_expiration_str = ''
            if loc.block_expiration_date:
                block_expiration_str = loc.block_expiration_date.strftime('%Y-%m-%d')

            is_expired_str = 'Sí' if loc.is_block_expired else 'No'

            oversized_from = loc.oversized_from_location_id.complete_name if (loc.block_reason_type == 'sobredimensionada' and loc.oversized_from_location_id) else ''

            writer.writerow([
                loc.complete_name or '',
                'Sí' if loc.original_parent_id else 'No',
                loc.original_parent_id.complete_name or '',
                oversized_from,
                loc.block_reason or '',
                loc.block_user_id.name or '',
                block_date_str,
                block_expiration_str,
                is_expired_str,
                pasillo,
                posicion,
                frente,
                nivel
            ])

        csv_content = output.getvalue()
        output.close()

        # Generate filename with date
        filename = f'reporte_posiciones_bloqueadas_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'

        # Prepend UTF-8 BOM to ensure Excel opens special characters correctly
        csv_bytes = b'\xef\xbb\xbf' + csv_content.encode('utf-8')

        # Return HTTP response
        return request.make_response(
            csv_bytes,
            headers=[
                ('Content-Type', 'text/csv; charset=utf-8'),
                ('Content-Disposition', content_disposition(filename))
            ]
        )

    @http.route('/wmds/v2/engine/location_blocking/search', type='json', auth='user', methods=['POST'])
    def location_blocking_search(self, term='', only_blocked=False, **kwargs):
        domain = [('usage', '=', 'internal')]
        if only_blocked:
            domain.append(('original_parent_id', '!=', False))
            
        if term:
            domain.append('|')
            domain.append(('name', 'ilike', term))
            domain.append(('complete_name', 'ilike', term))
            locations = request.env['stock.location'].sudo().search(domain, limit=100)
        else:
            import re
            f = {
                'a_from': str(kwargs.get('aisle_from', 'A')).upper(),
                'a_to': str(kwargs.get('aisle_to', 'Z')).upper(),
                'p_from': int(kwargs.get('position_from', 1)),
                'p_to': int(kwargs.get('position_to', 99)),
                'l_from': int(kwargs.get('level_from', 1)),
                'l_to': int(kwargs.get('level_to', 5)),
                'f_from': int(kwargs.get('front_from', 1)),
                'f_to': int(kwargs.get('front_to', 2)),
            }
            
            loc_pattern = re.compile(r"([A-Z]{1,2})-P(\d{2})-F(\d)-N(\d)$", re.IGNORECASE)

            def aisle_to_key(val):
                return (len(val), val)

            def is_location_in_range(name):
                match = loc_pattern.search(name or '')
                if not match:
                    return False
                
                aisle, pos, front, level = match.groups()
                aisle = aisle.upper()
                pos, front, level = int(pos), int(front), int(level)

                if not (aisle_to_key(f['a_from']) <= aisle_to_key(aisle) <= aisle_to_key(f['a_to'])):
                    return False
                if not (f['p_from'] <= pos <= f['p_to']):
                    return False
                if not (f['f_from'] <= front <= f['f_to']):
                    return False
                if not (f['l_from'] <= level <= f['l_to']):
                    return False
                
                return True

            all_locs = request.env['stock.location'].sudo().search(domain)
            locations = all_locs.filtered(lambda u: is_location_in_range(u.name))[:100]
            
        res = []
        for loc in locations:
            res.append({
                'id': loc.id,
                'name': loc.name,
                'complete_name': loc.complete_name,
                'is_blocked': bool(loc.original_parent_id),
                'block_reason_type': loc.block_reason_type or '',
                'block_reason': loc.block_reason or '',
                'block_user': loc.block_user_id.name or '',
                'block_date': loc.block_date.strftime('%Y-%m-%d %H:%M:%S') if loc.block_date else '',
                'block_expiration_date': loc.block_expiration_date.strftime('%Y-%m-%d') if loc.block_expiration_date else '',
                'is_block_expired': loc.is_block_expired,
                'oversized_from': loc.oversized_from_location_id.name or '',
                'oversized_to': ', '.join(loc.oversized_location_ids.mapped('name')) or '',
                'is_empty_location': loc.is_empty_location,
            })
        return res

    @http.route('/wmds/v2/engine/location_blocking/get_adjacent', type='json', auth='user', methods=['POST'])
    def location_blocking_get_adjacent(self, location_id, **kwargs):
        loc = request.env['stock.location'].sudo().browse(int(location_id))
        if not loc.exists():
            return []
        
        def parse_parts(name):
            parts = (name or '').split('-')
            if len(parts) == 4:
                try:
                    pasillo = parts[0]
                    pos_num = int(parts[1].replace('P', '').replace('p', ''))
                    frente_num = int(parts[2].replace('F', '').replace('f', ''))
                    nivel_num = int(parts[3].replace('N', '').replace('n', ''))
                    return pasillo, pos_num, frente_num, nivel_num
                except ValueError:
                    return None
            return None
            
        target_parsed = parse_parts(loc.name)
        if not target_parsed:
            return []
            
        t_pasillo, t_pos, t_frente, t_nivel = target_parsed
        
        candidates = request.env['stock.location'].sudo().search([
            ('id', '!=', loc.id),
            ('usage', '=', 'internal'),
        ])
        
        adjacents = []
        for cand in candidates:
            cand_parsed = parse_parts(cand.name)
            if cand_parsed:
                c_pasillo, c_pos, c_frente, c_nivel = cand_parsed
                if c_pasillo == t_pasillo:
                    dist_pos = abs(c_pos - t_pos)
                    dist_frente = abs(c_frente - t_frente)
                    dist_nivel = abs(c_nivel - t_nivel)
                    
                    if dist_pos <= 2 and dist_frente <= 1 and dist_nivel <= 2:
                        adjacents.append({
                            'id': cand.id,
                            'name': cand.name,
                            'complete_name': cand.complete_name,
                            'pos_offset': c_pos - t_pos,
                            'frente_offset': c_frente - t_frente,
                            'nivel_offset': c_nivel - t_nivel,
                            'is_blocked': bool(cand.original_parent_id),
                            'has_product': not cand.is_empty_location,
                        })
        return adjacents

    @http.route('/wmds/v2/engine/location_blocking/block', type='json', auth='user', methods=['POST'])
    def location_blocking_block(self, location_ids, block_reason_type, comment=None, ticket=None, expiration_date=None, original_location_id=None, **kwargs):
        locations = request.env['stock.location'].sudo().browse(location_ids)
        if not locations:
            return {'status': 'error', 'message': 'No se encontraron las ubicaciones a bloquear.'}
            
        try:
            if block_reason_type == 'sobredimensionada':
                if not original_location_id:
                    return {'status': 'error', 'message': 'Se requiere una ubicación original para el bloqueo por sobredimensionado.'}
                
                wizard = request.env['wb.stock.location.oversized.wizard'].sudo().create({
                    'original_location_id': int(original_location_id),
                    'location_ids': [(6, 0, location_ids)]
                })
                wizard.with_user(request.env.user).action_block_oversized()
            else:
                wizard = request.env['wb.stock.location.block.wizard'].sudo().create({
                    'location_ids': [(6, 0, location_ids)],
                    'block_reason_type': block_reason_type,
                    'comment': comment or '',
                    'ticket': ticket or '',
                    'expiration_date': expiration_date or False,
                })
                wizard.with_user(request.env.user).action_block()
                
            return {'status': 'ok'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    @http.route('/wmds/v2/engine/location_blocking/unblock', type='json', auth='user', methods=['POST'])
    def location_blocking_unblock(self, location_id, **kwargs):
        loc = request.env['stock.location'].sudo().browse(int(location_id))
        if not loc.exists():
            return {'status': 'error', 'message': 'No existe la ubicación.'}
            
        try:
            # Cancel oversized blocking if this location is currently oversizing others
            blocked_adjacents = request.env['stock.location'].sudo().search([
                ('oversized_from_location_id', '=', loc.id)
            ])
            if blocked_adjacents:
                if not request.env.user.has_group('stock.group_stock_user'):
                    return {'status': 'error', 'message': "Solo un Operador de inventario puede desbloquear esta ubicación."}
                for adj in blocked_adjacents:
                    adj.with_user(request.env.user)._do_unblock(comment=f"Desbloqueado al liberar la sobredimensión de {loc.name}.")
                return {'status': 'ok'}

            is_quarantine = (
                loc.block_reason_type == 'cuarentena' or
                (loc.block_reason and 'cuarentena' in loc.block_reason.lower()) or
                (loc.location_id and 'cuarentena' in (loc.location_id.complete_name or '').lower())
            )
            if is_quarantine:
                return {'status': 'error', 'message': 'No se permite desbloquear manualmente una ubicación en cuarentena.'}

            if loc.block_reason_type == 'ciclico':
                return {'status': 'error', 'message': 'No se permite desbloquear manualmente una ubicación en conteo cíclico. Debe salir del conteo cíclico de WMDS.'}

            if loc.block_reason_type in ('no_apto', 'danado', 'onsite'):
                if not request.env.user.has_group('wb_tech_location_blocking.group_lider_de_turno'):
                    liders = request.env.ref('wb_tech_location_blocking.group_lider_de_turno').users.mapped('name')
                    return {'status': 'error', 'message': f"Solo el Líder de turno puede realizar esta acción. Solicita a alguno de los siguientes usuarios que desbloqueen esta ubicación: {', '.join(liders)}"}
            elif loc.block_reason_type == 'sobredimensionada':
                if not request.env.user.has_group('stock.group_stock_user'):
                    return {'status': 'error', 'message': "Solo un Operador de inventario puede desbloquear esta ubicación."}

            loc.with_user(request.env.user)._do_unblock(comment='Desbloqueo completado desde WMDS.')
            return {'status': 'ok'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
