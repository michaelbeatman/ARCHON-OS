"""Layer-SSOT fuer geteilte Operations-Konstanten und -Helfer (F4).

Historisch lagen ``TEAMS_DEFINITION`` und ``_get_org_hierarchy_file()`` in
``archon/routers/operations_org.py``; ``backend/operations_api.py`` bezog sie
ueber einen der 125 Re-Exports. Weil ``backend`` ``archon.routers`` nicht
importieren darf (D09/H-09-2, siehe ``.importlinter``), liegt die SSOT jetzt
hier. Der Router re-exportiert beide Namen unveraendert weiter, damit alle
bestehenden Aufrufer unveraendert bleiben.
"""

import os

# Repo-Root, identisch zu backend/operations_api.py:87 (beide Module liegen
# direkt unter backend/). Frueher bezog operations_org.py diesen Wert ueber
# _get_ops_deps() aus operations_api; hier steht er als eigene Konstante.
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEAMS_DEFINITION = [
    {
        "id": "team_strategy",
        "name": "Geschäftsführung, Strategie & M&A",
        "lead_id": "executive_decision_architect",
        "color": "indigo",
        "members": [
            "executive_decision_architect",
            "micha",
            "default",
            "red_team_challenger",
            "tax_holding_advisor",
            "finance_lead",
            "debt_financing_specialist",
            "pricing_discount_governor",
            "pitchdeck_offer_designer",
            "personal_life_strategist",
            "research_scout",
            "hr_recruiter",
            "aggregation_lisa",
            "knowledge_librarian",
        ],
    },
    {
        "id": "team_tech",
        "name": "Software, Cloud, QA & Data",
        "lead_id": "system_architect_orchestrator",
        "color": "blue",
        "members": [
            "system_architect_orchestrator",
            "senior_fullstack_engineer",
            "qa_test_engineer",
            "devops_cloud_sec_specialist",
            "database_performance_tuner",
            "enterprise_solutions_architect",
            "bi_controller",
        ],
    },
    {
        "id": "team_legal",
        "name": "Recht, Versicherung & Governance",
        "lead_id": "commercial_jurist_contracts",
        "color": "amber",
        "members": [
            "commercial_jurist_contracts",
            "legal_counsel",
            "insurance_claims_manager",
            "liability_risk_analyst",
            "compliance_gdpr_auditor",
            "labor_law_hr_governance",
            "ip_patent_analyst",
            "vendor_contract_negotiator",
        ],
    },
    {
        "id": "team_realestate",
        "name": "Bau, Immobilien & ESG",
        "lead_id": "construction_project_manager",
        "color": "emerald",
        "members": [
            "construction_project_manager",
            "baugb_permit_expert",
            "realestate_dcf_calculator",
            "realestate_concept_strategist",
            "esg_kfw_efficiency_auditor",
            "urban_planning_architect",
            "vvgmbh_immo_tax_lead",
            "facility_asset_manager",
        ],
    },
    {
        "id": "team_growth",
        "name": "Vertrieb, Marketing, SEO & Media",
        "lead_id": "gtm_launch_strategist",
        "color": "rose",
        "members": [
            "gtm_launch_strategist",
            "growth_hacker_lead",
            "paid_ads_manager",
            "seo_geo_specialist",
            "telegram_bot",
            "b2b_outreach_specialist",
            "direct_response_copywriter",
            "storyteller_ghostwriter",
            "linkedin_social_media_specialist",
            "video_script_architect",
            "content_repurposing_specialist",
            "speechwriter_keynote_designer",
            "pr_press_communicator",
            "affiliate_partner_manager",
            "ecommerce_shopify_lead",
            "lead_enrichment_analyst",
            "customer_retention_specialist",
            "customer_support_lead",
            "brand_uiux_director",
        ],
    },
    {
        "id": "team_operations",
        "name": "Supply Chain, Einkauf & Scrum",
        "lead_id": "logistics_supply_chain_manager",
        "color": "teal",
        "members": [
            "logistics_supply_chain_manager",
            "procurement_sourcing_scout",
            "inventory_stock_forecaster",
            "agile_scrum_master",
            "product_requirements_engineer",
            "negotiation_master",
            "arbitrage_market_analyst",
            "competitive_intelligence_scout",
            "crisis_escalation_lead",
        ],
    },
    {
        "id": "team_science",
        "name": "Medizin, Chemie, Wissenschaft & Engineering",
        "lead_id": "clinical_medical_advisor",
        "color": "purple",
        "members": [
            "clinical_medical_advisor",
            "medtech_regulatory_lead",
            "chemistry_materials_specialist",
            "pharma_biotech_scientist",
            "scientific_literature_synthesizer",
            "industrial_process_engineer",
        ],
    },
]


def _get_org_hierarchy_file() -> str:
    """Pfad der Org-Hierarchie - identisch zur frueheren Router-Funktion.

    Die alte Implementierung in operations_org.py las WORKSPACE_DIR ueber
    _get_ops_deps() aus backend.operations_api. Beide Werte sind derselbe
    Repo-Root; die Abbildung bleibt 1:1 (config/org_hierarchy.json).
    """
    return os.path.join(WORKSPACE_DIR, "config", "org_hierarchy.json")