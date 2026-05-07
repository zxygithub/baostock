"""Configuration constants for the BaoStock data download project.

This module contains technical constants, field definitions, and paths
that rarely change. User-configurable settings (enabled switches, date ranges,
batch parameters) are in config.yaml and accessed via src.config_loader.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DB_PATH: Path = Path(__file__).parent.parent / "data" / "baostock.db"

# ---------------------------------------------------------------------------
# Internal timing settings (not user-configurable)
# ---------------------------------------------------------------------------

FINANCIAL_SLEEP: float = 0.5  # seconds between financial API calls
LOGIN_REFRESH_INTERVAL: int = 1800  # seconds (30 min) before re-login
MAX_RETRIES: int = 3  # maximum number of retry attempts

# ---------------------------------------------------------------------------
# Index codes
# ---------------------------------------------------------------------------

INDEX_CODES: list[str] = [
    "sh.000001",  # 上证综指
    "sh.000002",  # 上证A股
    "sh.000003",  # 上证B股
    "sz.399001",  # 深证成指
    "sz.399006",  # 创业板指
    "sh.000300",  # 沪深300
    "sh.000905",  # 中证500
    "sz.399005",  # 中小板指
]

# ---------------------------------------------------------------------------
# K-line field definitions
# ---------------------------------------------------------------------------

DAILY_KLINE_FIELDS: str = (
    "date,code,open,high,low,close,preclose,volume,amount,"
    "adjustflag,turn,tradestatus,pctChg,peTTM,pbMRQ,psTTM,"
    "pcfNcfTTM,isST"
)

WEEKLY_MONTHLY_KLINE_FIELDS: str = (
    "date,code,open,high,low,close,volume,amount,adjustflag,turn,pctChg"
)

MINUTE_KLINE_FIELDS: str = "date,time,code,open,high,low,close,volume,amount,adjustflag"

INDEX_DAILY_FIELDS: str = "date,code,open,high,low,close,preclose,volume,amount,pctChg"

INDEX_WEEKLY_MONTHLY_FIELDS: str = (
    "date,code,open,high,low,close,volume,amount,adjustflag,turn,pctChg"
)

# ---------------------------------------------------------------------------
# Column rename mappings (BaoStock camelCase → snake_case)
# ---------------------------------------------------------------------------

RENAME_KLINE: dict[str, str] = {
    "pctChg": "pct_chg",
    "peTTM": "pe_ttm",
    "pbMRQ": "pb_mrq",
    "psTTM": "ps_ttm",
    "pcfNcfTTM": "pcf_ncf_ttm",
    "isST": "is_st",
}

RENAME_META: dict[str, str] = {
    "ipoDate": "ipo_date",
    "outDate": "out_date",
}

RENAME_INDUSTRY: dict[str, str] = {
    "industryClassification": "industry_classification",
    "updateDate": "update_date",
}

RENAME_COMPONENT: dict[str, str] = {"updateDate": "update_date"}

RENAME_DIVIDEND: dict[str, str] = {
    "dividPreNoticeDate": "divid_pre_notice_date",
    "dividAgmPumDate": "divid_agm_pum_date",
    "dividPlanAnnounceDate": "divid_plan_announce_date",
    "dividPlanDate": "divid_plan_date",
    "dividRegistDate": "divid_regist_date",
    "dividOperateDate": "divid_operate_date",
    "dividPayDate": "divid_pay_date",
    "dividStockMarketDate": "divid_stock_market_date",
    "dividCashPsBeforeTax": "divid_cash_ps_before_tax",
    "dividCashPsAfterTax": "divid_cash_ps_after_tax",
    "dividStocksPs": "divid_stocks_ps",
    "dividCashStock": "divid_cash_stock",
    "dividReserveToStockPs": "divid_reserve_to_stock_ps",
}

RENAME_ADJUST_FACTOR: dict[str, str] = {
    "dividOperateDate": "divid_operate_date",
    "foreAdjustFactor": "fore_adjust_factor",
    "backAdjustFactor": "back_adjust_factor",
    "adjustFactor": "adjust_factor",
}

RENAME_PROFIT: dict[str, str] = {
    "pubDate": "pub_date",
    "statDate": "stat_date",
    "roeAvg": "roe_avg",
    "npMargin": "np_margin",
    "gpMargin": "gp_margin",
    "netProfit": "net_profit",
    "epsTTM": "eps_ttm",
    "MBRevenue": "mb_revenue",
    "totalShare": "total_share",
    "liqaShare": "liqa_share",
}

RENAME_OPERATION: dict[str, str] = {
    "pubDate": "pub_date",
    "statDate": "stat_date",
    "NRTurnRatio": "nr_turn_ratio",
    "NRTurnDays": "nr_turn_days",
    "INVTurnRatio": "inv_turn_ratio",
    "INVTurnDays": "inv_turn_days",
    "CATurnRatio": "ca_turn_ratio",
    "AssetTurnRatio": "asset_turn_ratio",
}

RENAME_GROWTH: dict[str, str] = {
    "pubDate": "pub_date",
    "statDate": "stat_date",
    "YOYEquity": "yoy_equity",
    "YOYAsset": "yoy_asset",
    "YOYNI": "yoy_ni",
    "YOYEPSBasic": "yoy_eps_basic",
    "YOYPNI": "yoy_pni",
}

RENAME_BALANCE: dict[str, str] = {
    "pubDate": "pub_date",
    "statDate": "stat_date",
    "currentRatio": "current_ratio",
    "quickRatio": "quick_ratio",
    "cashRatio": "cash_ratio",
    "YOYLiability": "yoy_liability",
    "liabilityToAsset": "liability_to_asset",
    "assetToEquity": "asset_to_equity",
}

RENAME_CASH_FLOW: dict[str, str] = {
    "pubDate": "pub_date",
    "statDate": "stat_date",
    "CAToAsset": "ca_to_asset",
    "NCAToAsset": "nca_to_asset",
    "tangibleAssetToAsset": "tangible_asset_to_asset",
    "ebitToInterest": "ebit_to_interest",
    "CFOToOR": "cfo_to_or",
    "CFOToNP": "cfo_to_np",
    "CFOToGr": "cfo_to_gr",
}

RENAME_DUPONT: dict[str, str] = {
    "pubDate": "pub_date",
    "statDate": "stat_date",
    "dupontROE": "dupont_roe",
    "dupontAssetStoEquity": "dupont_asset_to_equity",
    "dupontAssetTurn": "dupont_asset_turn",
    "dupontPnitoni": "dupont_pni_to_ni",
    "dupontNitogr": "dupont_ni_to_gr",
    "dupontTaxBurden": "dupont_tax_burden",
    "dupontIntburden": "dupont_int_burden",
    "dupontEbittogr": "dupont_ebit_to_gr",
}

RENAME_PERFORMANCE_EXPRESS: dict[str, str] = {
    "performanceExpPubDate": "performance_exp_pub_date",
    "performanceExpStatDate": "performance_exp_stat_date",
    "performanceExpUpdateDate": "performance_exp_update_date",
    "performanceExpressTotalAsset": "total_asset",
    "performanceExpressNetAsset": "net_asset",
    "performanceExpressEPSChgPct": "eps_chg_pct",
    "performanceExpressROEWa": "roe_wa",
    "performanceExpressEPSDiluted": "eps_diluted",
    "performanceExpressGRYOY": "gr_yoy",
    "performanceExpressOPYOY": "op_yoy",
}

RENAME_FORECAST_REPORT: dict[str, str] = {
    "profitForcastExpPubDate": "profit_forecast_exp_pub_date",
    "profitForcastExpStatDate": "profit_forecast_exp_stat_date",
    "profitForcastType": "profit_forecast_type",
    "profitForcastAbstract": "profit_forecast_abstract",
    "profitForcastChgPctUp": "profit_forecast_chg_pct_up",
    "profitForcastChgPctDwn": "profit_forecast_chg_pct_down",
}

RENAME_DEPOSIT_RATE: dict[str, str] = {
    "pubDate": "pub_date",
    "demandDepositRate": "demand_deposit_rate",
    "fixedDepositRate3Month": "fixed_deposit_rate_3_month",
    "fixedDepositRate6Month": "fixed_deposit_rate_6_month",
    "fixedDepositRate1Year": "fixed_deposit_rate_1_year",
    "fixedDepositRate2Year": "fixed_deposit_rate_2_year",
    "fixedDepositRate3Year": "fixed_deposit_rate_3_year",
    "fixedDepositRate5Year": "fixed_deposit_rate_5_year",
    "installmentFixedDepositRate1Year": "installment_fixed_rate_1_year",
    "installmentFixedDepositRate3Year": "installment_fixed_rate_3_year",
    "installmentFixedDepositRate5Year": "installment_fixed_rate_5_year",
}

RENAME_LOAN_RATE: dict[str, str] = {
    "pubDate": "pub_date",
    "loanRate6Month": "loan_rate_6_month",
    "loanRate6MonthTo1Year": "loan_rate_6m_to_1y",
    "loanRate1YearTo3Year": "loan_rate_1y_to_3y",
    "loanRate3YearTo5Year": "loan_rate_3y_to_5y",
    "loanRateAbove5Year": "loan_rate_above_5y",
    "mortgateRateBelow5Year": "mortgage_rate_below_5y",
    "mortgateRateAbove5Year": "mortgage_rate_above_5y",
}

RENAME_RESERVE_RATIO: dict[str, str] = {
    "pubDate": "pub_date",
    "effectiveDate": "effective_date",
    "bigInstitutionsRatioPre": "big_institutions_ratio_pre",
    "bigInstitutionsRatioAfter": "big_institutions_ratio_after",
    "mediumInstitutionsRatioPre": "medium_institutions_ratio_pre",
    "mediumInstitutionsRatioAfter": "medium_institutions_ratio_after",
}

RENAME_MONEY_SUPPLY_MONTH: dict[str, str] = {
    "statYear": "stat_year",
    "statMonth": "stat_month",
    "m0Month": "m0_month",
    "m0YOY": "m0_yoy",
    "m0ChainRelative": "m0_chain",
    "m1Month": "m1_month",
    "m1YOY": "m1_yoy",
    "m1ChainRelative": "m1_chain",
    "m2Month": "m2_month",
    "m2YOY": "m2_yoy",
    "m2ChainRelative": "m2_chain",
}

RENAME_MONEY_SUPPLY_YEAR: dict[str, str] = {
    "statYear": "stat_year",
    "m0Year": "m0_year",
    "m0YearYOY": "m0_year_yoy",
    "m1Year": "m1_year",
    "m1YearYOY": "m1_year_yoy",
    "m2Year": "m2_year",
    "m2YearYOY": "m2_year_yoy",
}
