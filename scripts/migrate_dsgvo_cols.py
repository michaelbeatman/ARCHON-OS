import sqlite3

def migrate():
    conn = sqlite3.connect('pocketbase/pb_data/data.db')
    cursor = conn.cursor()
    cols = [r[1] for r in cursor.execute('PRAGMA table_info(kontakte)').fetchall()]

    new_cols = [
        ('dsgvo_legal_basis', "TEXT DEFAULT 'art6_1_f'"),
        ('dsgvo_opt_email', "INTEGER DEFAULT 1"),
        ('dsgvo_opt_phone', "INTEGER DEFAULT 1"),
        ('dsgvo_opt_postal', "INTEGER DEFAULT 0"),
        ('dsgvo_opt_source', "TEXT DEFAULT 'B2B Erstkontakt / LinkedIn'"),
        ('dsgvo_opt_out', "INTEGER DEFAULT 0"),
        ('dsgvo_opt_out_date', "TEXT DEFAULT ''"),
        ('dsgvo_retention_category', "TEXT DEFAULT 'commercial_10y'")
    ]

    for col_name, col_type in new_cols:
        if col_name not in cols:
            print(f'Adding {col_name}...')
            cursor.execute(f'ALTER TABLE kontakte ADD COLUMN {col_name} {col_type}')

    conn.commit()
    cols_after = [r[1] for r in cursor.execute('PRAGMA table_info(kontakte)').fetchall()]
    print('Done. Total columns now:', len(cols_after))
    conn.close()

if __name__ == '__main__':
    migrate()
