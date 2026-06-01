# -*- coding: utf-8 -*-
{
    'name': "WB Tech Location Blocking",
    'summary': "Technical Module for Stock Location Blocking",
    'description': """
    Technical module to manage the blocking of stock locations in Wonderbrands.
    """,
    'author': "Wonderbrands",
    'website': "https://www.wonderbrands.co",
    'category': 'Technical',
    'version': '18.0',
    'depends': [
        'base',
        'web',
        'website',
        'portal',
        'stock',
        'stock_barcode',
        'purchase',
        'WB_data_sale_order',
        'wmds'
    ],
    'external_dependencies': {
        'python': [
            'qrcode',
        ],
    },
    'data': [
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'data/location_blocked_data.xml',
        'data/location_blocking_migration.xml',
        'views/stock_location_views.xml',
        'views/stock_location_block_wizard_views.xml',
        'views/stock_location_unblock_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
