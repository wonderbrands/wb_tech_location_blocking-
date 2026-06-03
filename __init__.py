# -*- coding: utf-8 -*-
from . import models
from . import controllers
import logging

_logger = logging.getLogger(__name__)

def post_init_hook(env):
    """
    Migration: Move currently blocked locations directly under the old 'Bloqueado/'
    parent to the new sub-child locations ('Ciclico' or 'NoApta') based on their
    assigned block_reason_type or by inferring it from block_reason.
    """
    _logger.info("Starting stock location blocking migration...")
    
    # 1. Get base 'Bloqueado' location
    wmds_blocked = env.ref('wmds.location_blocked', raise_if_not_found=False)
    if not wmds_blocked:
        _logger.warning("Base blocked location 'wmds.location_blocked' not found. Skipping migration.")
        return

    # 2. Get the new sub-child locations
    ciclico_dest = env.ref('wb_tech_location_blocking.location_blocked_ciclico', raise_if_not_found=False)
    no_apto_dest = env.ref('wb_tech_location_blocking.location_blocked_no_apto', raise_if_not_found=False)
    danado_dest = env.ref('wb_tech_location_blocking.location_blocked_danado', raise_if_not_found=False)
    onsite_dest = env.ref('wb_tech_location_blocking.location_blocked_onsite', raise_if_not_found=False)
    
    if not ciclico_dest or not no_apto_dest:
        _logger.warning("Sub-child blocked locations not found. Skipping migration.")
        return

    # 3. Find all locations currently directly under the old 'Bloqueado/' parent
    blocked_locations = env['stock.location'].search([
        ('location_id', '=', wmds_blocked.id)
    ])
    
    _logger.info("Found %d locations under the old Bloqueado parent to migrate.", len(blocked_locations))
    
    for loc in blocked_locations:
        # Determine block reason type
        reason_type = loc.block_reason_type
        
        # If block_reason_type is not set, try to infer it from the textual block_reason
        if not reason_type:
            reason_text = (loc.block_reason or '').lower()
            if any(x in reason_text for x in ['dañado', 'danado', 'dañada', 'daña']):
                reason_type = 'danado'
            elif any(x in reason_text for x in ['onsite', 'on-site']):
                reason_type = 'onsite'
            elif any(x in reason_text for x in ['no apto', 'no_apto', 'mantenimiento', 'incidencia', 'daño', 'daño estructural']):
                reason_type = 'no_apto'
            else:
                reason_type = 'ciclico'
        
        # Choose destination sub-child location
        dest_loc = ciclico_dest
        if reason_type == 'no_apto':
            dest_loc = no_apto_dest
        elif reason_type == 'danado' and danado_dest:
            dest_loc = danado_dest
        elif reason_type == 'onsite' and onsite_dest:
            dest_loc = onsite_dest
        
        # Set values to write
        vals = {
            'location_id': dest_loc.id,
            'block_reason_type': reason_type,
        }
        
        # Ensure block_reason is set
        if not loc.block_reason:
            vals['block_reason'] = f"Bloqueado/{dict(loc._fields['block_reason_type'].selection).get(reason_type, 'Cíclico')}"

        # If original_parent_id is missing, try to keep it safe (though it should already be set)
        if not loc.original_parent_id:
            # If we don't know the original parent, we leave it as is or fallback to WH/Stock if needed,
            # but usually it's set in the old system.
            pass
            
        loc.sudo().write(vals)
        _logger.info("Migrated location %s to %s with reason type %s", loc.complete_name, dest_loc.name, reason_type)

    _logger.info("Stock location blocking migration finished successfully.")
