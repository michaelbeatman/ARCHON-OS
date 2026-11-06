# Autonom synthetisiert von tax_holding_advisor am 2026-11-05T14:06:02.969035

def calculate_vat_split(gross_amount: float, tax_rate: float = 0.19):
    net = round(gross_amount / (1.0 + tax_rate), 2)
    tax = round(gross_amount - net, 2)
    return {"gross": gross_amount, "net": net, "tax": tax}
