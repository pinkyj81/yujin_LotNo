import calendar
import logging
import os
from datetime import datetime, timedelta

import pyodbc
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
FRACTURE_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "fracture")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(FRACTURE_UPLOAD_DIR, exist_ok=True)


def get_env_value(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return default


def build_connection_string(prefix: str = "DB") -> str:
    server = get_env_value(f"{prefix}_SERVER")
    port = get_env_value(f"{prefix}_PORT", default="1433")
    database = get_env_value(f"{prefix}_NAME", f"{prefix}_DATABASE")
    username = get_env_value(f"{prefix}_USER", f"{prefix}_USERNAME")
    password = get_env_value(f"{prefix}_PASSWORD")
    driver = get_env_value(f"{prefix}_DRIVER", default="ODBC Driver 18 for SQL Server")

    if not all([server, database, username, password]):
        raise ValueError(f"Missing required {prefix} connection settings in .env")

    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server},{port};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        "TrustServerCertificate=yes;"
    )


def build_yujin_reference_connection_string() -> str:
    server = get_env_value("YUJIN_DB_SERVER", default="ms0501.gabiadb.com")
    port = get_env_value("YUJIN_DB_PORT", default="1433")
    database = get_env_value("YUJIN_DB_NAME", "YUJIN_DB_DATABASE", default="yujin")
    username = get_env_value("YUJIN_DB_USER", "YUJIN_DB_USERNAME", default="yujin")
    password = get_env_value("YUJIN_DB_PASSWORD", default="yj8630")
    driver = get_env_value("YUJIN_DB_DRIVER", default="ODBC Driver 18 for SQL Server")
    encrypt = get_env_value("YUJIN_DB_ENCRYPT", default="no")
    trust_server_cert = get_env_value("YUJIN_DB_TRUST_SERVER_CERTIFICATE", default="yes")

    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server},{port};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"Encrypt={encrypt};"
        f"TrustServerCertificate={trust_server_cert};"
    )


def build_yujincast_reference_connection_string() -> str:
    server = get_env_value("YUJINCAST_DB_SERVER", default="ms1901.gabiadb.com")
    port = get_env_value("YUJINCAST_DB_PORT", default="1433")
    database = get_env_value("YUJINCAST_DB_NAME", "YUJINCAST_DB_DATABASE", default="yujincast")
    username = get_env_value("YUJINCAST_DB_USER", "YUJINCAST_DB_USERNAME", default="pinkyj81")
    password = get_env_value("YUJINCAST_DB_PASSWORD", default="zoskek38!!")
    driver = get_env_value("YUJINCAST_DB_DRIVER", default="ODBC Driver 18 for SQL Server")
    encrypt = get_env_value("YUJINCAST_DB_ENCRYPT", default="yes")
    trust_server_cert = get_env_value("YUJINCAST_DB_TRUST_SERVER_CERTIFICATE", default="yes")

    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server},{port};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        f"Encrypt={encrypt};"
        f"TrustServerCertificate={trust_server_cert};"
    )


def get_db_connection(prefix: str = "DB"):
    if prefix == "YUJIN_DB":
        last_error = None
        try:
            conn_str = build_connection_string(prefix)
            return pyodbc.connect(conn_str, timeout=5)
        except Exception as exc:
            last_error = exc
            conn_str = build_yujin_reference_connection_string()
            try:
                return pyodbc.connect(conn_str, timeout=5)
            except Exception as fallback_exc:
                last_error = fallback_exc

                # ODBC 18이 실패하면 구형 서버 호환을 위해 Driver 17도 시도.
                alt_conn_str = conn_str.replace("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server")
                if alt_conn_str != conn_str:
                    return pyodbc.connect(alt_conn_str, timeout=5)

        if last_error:
            raise last_error

    if prefix == "YUJINCAST_DB":
        try:
            conn_str = build_connection_string(prefix)
        except ValueError:
            conn_str = build_yujincast_reference_connection_string()
        return pyodbc.connect(conn_str, timeout=5)

    return pyodbc.connect(build_connection_string(prefix), timeout=5)


def get_reference_db_prefixes() -> list[str]:
    return ["YUJIN_DB", "YUJINCAST_DB"]


def fetch_dict_rows(cursor, query: str, params=None):
    cursor.execute(query, params or [])
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def normalize_lot(lot_value: str | None) -> str:
    if not lot_value:
        return ""
    return str(lot_value).replace(".", "").replace("-", "").replace(" ", "").upper()


def format_quantity(value):
    if value is None or value == "":
        return "-"
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return str(value)


def get_default_dates() -> tuple[str, str]:
    today = datetime.now()
    month_start = today.replace(day=1).strftime("%Y-%m-%d")
    month_end = today.replace(day=calendar.monthrange(today.year, today.month)[1]).strftime("%Y-%m-%d")
    return month_start, month_end


def try_load_reference_data():
    company_map = {}
    product_map = {}
    chemical_lots = set()

    for prefix in get_reference_db_prefixes():
        try:
            with get_db_connection(prefix) as conn:
                with conn.cursor() as cursor:
                    company_rows = fetch_dict_rows(cursor, "SELECT CustCode, CustName FROM dbo.Custinfo")
                    product_rows = fetch_dict_rows(cursor, "SELECT CodeNo, CodeName FROM dbo.PCodeinfo")
                    chemical_rows = fetch_dict_rows(cursor, "SELECT DISTINCT LotNo FROM dbo.Chemicalinfo")

            company_map = {row["CustCode"]: row["CustName"] for row in company_rows}
            product_map = {row["CodeNo"]: row["CodeName"] for row in product_rows}
            chemical_lots = {normalize_lot(row.get("LotNo")) for row in chemical_rows if row.get("LotNo")}
            return company_map, product_map, chemical_lots
        except Exception as exc:
            logger.warning("reference data load failed (%s): %s", prefix, exc)

    return company_map, product_map, chemical_lots


def load_form_options():
    companies = []

    for prefix in get_reference_db_prefixes():
        try:
            with get_db_connection(prefix) as conn:
                with conn.cursor() as cursor:
                    companies = fetch_dict_rows(
                        cursor,
                        """
                        SELECT CustCode, CustName
                        FROM dbo.Custinfo
                        WHERE LTRIM(RTRIM(ISNULL(CustCode, ''))) <> ''
                          AND LTRIM(RTRIM(ISNULL(mgubun1, ''))) = '001'
                        ORDER BY CustName
                        """,
                    )
            return companies
        except Exception as exc:
            logger.warning("company options load failed (%s): %s", prefix, exc)

    return companies


def load_products_by_company(company_code: str):
    if not company_code:
        return []

    query = """
        SELECT DISTINCT
            LTRIM(RTRIM(md.CodeNo)) AS CodeNo,
            LTRIM(RTRIM(ISNULL(pc.CodeName, ''))) AS CodeName
        FROM dbo.MatlDanGa md
        LEFT JOIN dbo.PCodeinfo pc ON LTRIM(RTRIM(md.CodeNo)) = LTRIM(RTRIM(pc.CodeNo))
        WHERE LTRIM(RTRIM(ISNULL(md.CustCode, ''))) = ?
          AND LTRIM(RTRIM(ISNULL(md.CodeNo, ''))) <> ''
        ORDER BY LTRIM(RTRIM(md.CodeNo))
    """

    for prefix in get_reference_db_prefixes():
        try:
            with get_db_connection(prefix) as conn:
                with conn.cursor() as cursor:
                    return fetch_dict_rows(cursor, query, [company_code])
        except Exception as exc:
            logger.warning("product lookup failed (%s): %s", prefix, exc)

    return []


def generate_lot_no(in_date):
    if not in_date:
        return "-"

    try:
        if isinstance(in_date, str):
            for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"]:
                try:
                    date_obj = datetime.strptime(in_date, fmt)
                    break
                except ValueError:
                    continue
            else:
                return "-"
        else:
            date_obj = in_date

        year_digit = str(date_obj.year)[-1]
        month_alpha = chr(ord("A") + date_obj.month - 1)
        day_str = f"{date_obj.day:02d}"
        return f"{year_digit}{month_alpha}{day_str}"
    except Exception:
        return "-"


def save_uploaded_file(file_storage, target_dir: str, allowed_extensions: set[str]):
    if not file_storage or not file_storage.filename:
        return None

    extension = os.path.splitext(file_storage.filename)[1].lower()
    if extension not in allowed_extensions:
        raise ValueError(f"허용되지 않는 파일 형식입니다: {extension}")

    filename = secure_filename(file_storage.filename)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    stored_name = f"{timestamp}_{filename}"
    file_storage.save(os.path.join(target_dir, stored_name))
    return stored_name


def get_inspections(filters: dict[str, str]):
    ensure_quality_inspection_columns()
    query = """
        SELECT
            qi.InspectionID,
            qi.ScreenType,
            qi.InspectionDate,
            qi.CompanyCode,
            qi.PartNumber,
            qi.Quantity,
            qi.BundleCount,
            qi.LotNo,
            qi.Inspector,
            qi.Result,
            qi.DefectCount,
            qi.Notes,
            qi.FilePath,
            qi.BreakFilePath
        FROM QualityInspection qi
        WHERE 1=1
    """
    params = []

    if filters["start_date"]:
        query += " AND CAST(qi.InspectionDate AS DATE) >= ?"
        params.append(filters["start_date"])
    if filters["end_date"]:
        query += " AND CAST(qi.InspectionDate AS DATE) <= ?"
        params.append(filters["end_date"])
    if filters["lot_no"]:
        query += " AND qi.LotNo LIKE ?"
        params.append(f"%{filters['lot_no']}%")

    query += " ORDER BY qi.InspectionDate DESC, qi.InspectionID DESC"

    with get_db_connection("DB") as conn:
        with conn.cursor() as cursor:
            rows = fetch_dict_rows(cursor, query, params)

    company_map, product_map, chemical_lots = try_load_reference_data()
    normalized_company = filters["company_name"].lower()
    normalized_product = filters["product_name"].lower()

    inspections = []
    for row in rows:
        company_name = company_map.get(row.get("CompanyCode"), "-")
        product_name = product_map.get(row.get("PartNumber")) or row.get("PartNumber") or "-"
        lot_no = row.get("LotNo") or "-"
        inspection_date = row.get("InspectionDate")
        if hasattr(inspection_date, "strftime"):
            inspection_date = inspection_date.strftime("%Y-%m-%d")

        inspection = {
            "InspectionID": row.get("InspectionID"),
            "ScreenType": "INGOT" if row.get("ScreenType") in ["INGOT", "인고트"] else (row.get("ScreenType") or "-"),
            "InspectionDate": inspection_date or "-",
            "CompanyCode": row.get("CompanyCode") or "-",
            "CompanyName": company_name,
            "PartNumber": row.get("PartNumber") or "-",
            "ProductName": product_name,
            "Quantity": int(float(row.get("Quantity") or 0)) if row.get("Quantity") not in [None, ""] else 0,
            "QuantityDisplay": format_quantity(row.get("Quantity")),
            "BundleCount": int(float(row.get("BundleCount") or 0)) if row.get("BundleCount") not in [None, ""] else 0,
            "BundleCountDisplay": format_quantity(row.get("BundleCount")),
            "LotNo": lot_no,
            "Inspector": row.get("Inspector") or "-",
            "Result": row.get("Result") or "-",
            "Notes": row.get("Notes") or "-",
            "FilePath": row.get("FilePath") or "",
            "BreakFilePath": row.get("BreakFilePath") or "",
            "HasChemical": normalize_lot(lot_no) in chemical_lots,
        }

        if normalized_company and normalized_company not in inspection["CompanyName"].lower():
            continue
        if normalized_product:
            haystacks = [inspection["PartNumber"].lower(), inspection["ProductName"].lower()]
            if not any(normalized_product in haystack for haystack in haystacks):
                continue

        inspections.append(inspection)

    return inspections


def get_traceability_mappings(filters: dict[str, str]):
    start_date = filters["start_date"]
    end_date = filters["end_date"]
    lotno_only = filters.get("lotno_only", False)
    company_name = (filters.get("company_name") or "").strip()
    product_name = (filters.get("product_name") or "").strip()

    with get_db_connection("YUJIN_DB") as conn:
        cursor = conn.cursor()

        mapping_dict = {}

        subul_query = """
            SELECT
                s.LotNo,
                pb.SojeNo,
                SUM(s.Qty) as TotalQty
            FROM subulinfo s
            INNER JOIN (
                SELECT DISTINCT
                    LTRIM(RTRIM(PCode)) AS PCode,
                    LTRIM(RTRIM(SojeNo)) AS SojeNo
                FROM dbo.ProdBom
                WHERE LTRIM(RTRIM(ISNULL(PCode, ''))) <> ''
                  AND LTRIM(RTRIM(ISNULL(SojeNo, ''))) <> ''
            ) pb ON LTRIM(RTRIM(ISNULL(s.CodeNo, ''))) = pb.PCode
            WHERE CONVERT(date, s.ChulDate) BETWEEN ? AND ?
                AND s.LotNo IS NOT NULL AND s.LotNo != ''
            GROUP BY s.LotNo, pb.SojeNo
        """
        cursor.execute(subul_query, [start_date, end_date])
        for row in cursor.fetchall():
            lot_list = [part.strip() for part in str(row.LotNo).split(",") if part.strip()]
            for single_lot in lot_list:
                key = f"{row.SojeNo}_{single_lot}"
                mapping_dict.setdefault(key, {
                    "SojeNo": row.SojeNo,
                    "LotNo": single_lot,
                    "SubulQty": 0,
                    "HeatQty": 0,
                    "ProdQty": 0,
                })
                mapping_dict[key]["SubulQty"] += float(row.TotalQty or 0)

        heat_query = """
            SELECT
                LotNo,
                CodeNo as SojeNo,
                SUM(Qty) as TotalQty
            FROM HeatSilJuk
            WHERE CONVERT(date, MDate) BETWEEN ? AND ?
                AND LotNo IS NOT NULL AND LotNo != ''
                AND CodeNo IS NOT NULL AND CodeNo != ''
            GROUP BY LotNo, CodeNo
        """
        cursor.execute(heat_query, [start_date, end_date])
        for row in cursor.fetchall():
            key = f"{row.SojeNo}_{row.LotNo}"
            mapping_dict.setdefault(key, {
                "SojeNo": row.SojeNo,
                "LotNo": row.LotNo,
                "SubulQty": 0,
                "HeatQty": 0,
                "ProdQty": 0,
            })
            mapping_dict[key]["HeatQty"] += float(row.TotalQty or 0)

        prod_query = """
            SELECT
                ps.InDate,
                ps.CodeNo as SojeNo,
                SUM(ps.Qty) as TotalQty
            FROM dbo.ProdSilJuk ps
            WHERE CONVERT(date, ps.InDate) BETWEEN ? AND ?
                AND ps.CodeNo IS NOT NULL AND ps.CodeNo != ''
            GROUP BY ps.InDate, ps.CodeNo
        """
        cursor.execute(prod_query, [start_date, end_date])
        for row in cursor.fetchall():
            generated_lot = generate_lot_no(row.InDate)
            if generated_lot == "-":
                continue
            key = f"{row.SojeNo}_{generated_lot}"
            mapping_dict.setdefault(key, {
                "SojeNo": row.SojeNo,
                "LotNo": generated_lot,
                "SubulQty": 0,
                "HeatQty": 0,
                "ProdQty": 0,
            })
            mapping_dict[key]["ProdQty"] += float(row.TotalQty or 0)

        mapping_list = sorted(mapping_dict.values(), key=lambda item: (str(item.get("SojeNo") or ""), str(item.get("LotNo") or "")))

        cust_name_by_code = {}
        pcode_map = {}

        cust_df = fetch_dict_rows(cursor, "SELECT CustCode, CustName FROM dbo.Custinfo")
        for row in cust_df:
            cust_code = str(row.get("CustCode") or "").strip().upper()
            cust_name = str(row.get("CustName") or "").strip()
            if cust_code and cust_name:
                cust_name_by_code[cust_code] = cust_name

        pcode_cols_df = fetch_dict_rows(cursor, "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'PCodeinfo'")
        pcode_cols = {str(row.get("COLUMN_NAME") or "").strip() for row in pcode_cols_df}
        code_col = "CodeNo" if "CodeNo" in pcode_cols else None
        product_col_candidates = ["CodeName", "ProdName", "ProductName", "PName", "ItemName"]
        company_name_col_candidates = ["CustName", "CompanyName", "BuyerName", "CustomerName", "Customer", "ClientName", "VendName", "VendorName"]
        company_code_col_candidates = ["CustCode", "CompanyCode", "BuyerCode", "CustomerCode", "Cust", "CustNo", "CustCd", "Customer", "ClientCode", "VendorCode", "VendCode"]

        if code_col:
            product_col = next((c for c in product_col_candidates if c in pcode_cols), None)
            company_name_col = next((c for c in company_name_col_candidates if c in pcode_cols), None)
            company_code_col = next((c for c in company_code_col_candidates if c in pcode_cols), None)

            select_cols = [f"[{code_col}] AS CodeNo"]
            select_cols.append(f"[{product_col}] AS ProductName" if product_col else "NULL AS ProductName")
            select_cols.append(f"[{company_name_col}] AS CompanyName" if company_name_col else "NULL AS CompanyName")
            select_cols.append(f"[{company_code_col}] AS CompanyCode" if company_code_col else "NULL AS CompanyCode")
            pcode_df = fetch_dict_rows(cursor, f"SELECT {', '.join(select_cols)} FROM dbo.PCodeinfo")

            for row in pcode_df:
                key = str(row.get("CodeNo") or "").strip().upper()
                if not key:
                    continue
                company_code = str(row.get("CompanyCode") or "").strip()
                company_name_raw = str(row.get("CompanyName") or "").strip()
                company_name_value = company_name_raw
                if company_code:
                    company_name_value = cust_name_by_code.get(company_code.upper(), company_name_raw)
                pcode_map[key] = {
                    "ProductName": str(row.get("ProductName") or "").strip(),
                    "CompanyName": company_name_value,
                    "CompanyCode": company_code,
                }

        try:
            soje_cust_df = fetch_dict_rows(cursor, """
                SELECT pb.SojeNo, s.CustCode, SUM(s.Qty) AS TotalQty
                FROM subulinfo s
                INNER JOIN (
                    SELECT DISTINCT
                        LTRIM(RTRIM(PCode)) AS PCode,
                        LTRIM(RTRIM(SojeNo)) AS SojeNo
                    FROM dbo.ProdBom
                    WHERE LTRIM(RTRIM(ISNULL(PCode, ''))) <> ''
                      AND LTRIM(RTRIM(ISNULL(SojeNo, ''))) <> ''
                ) pb ON LTRIM(RTRIM(ISNULL(s.CodeNo, ''))) = pb.PCode
                WHERE CONVERT(date, s.ChulDate) BETWEEN ? AND ?
                    AND s.CustCode IS NOT NULL AND s.CustCode != ''
                GROUP BY pb.SojeNo, s.CustCode
            """, [start_date, end_date])

            soje_top_cust_code = {}
            for row in soje_cust_df:
                soje_key = str(row.get("SojeNo") or "").strip().upper()
                cust_code = str(row.get("CustCode") or "").strip()
                qty = float(row.get("TotalQty") or 0)
                if not soje_key or not cust_code:
                    continue
                prev = soje_top_cust_code.get(soje_key)
                if prev is None or qty > prev[1]:
                    soje_top_cust_code[soje_key] = (cust_code, qty)

            for soje_key, (cust_code, _) in soje_top_cust_code.items():
                mapped = pcode_map.get(soje_key, {})
                if not str(mapped.get("CompanyName") or "").strip():
                    mapped["CompanyCode"] = mapped.get("CompanyCode") or cust_code
                    mapped["CompanyName"] = cust_name_by_code.get(cust_code.upper(), cust_code)
                    pcode_map[soje_key] = mapped
        except Exception:
            pass

        for item in mapping_list:
            soje_key = str(item.get("SojeNo") or "").strip().upper()
            mapped = pcode_map.get(soje_key, {})
            item["ProductName"] = mapped.get("ProductName") or "-"
            item["CompanyName"] = mapped.get("CompanyName") or mapped.get("CompanyCode") or "-"

        if lotno_only:
            mapping_list = [item for item in mapping_list if str(item.get("LotNo") or "").strip() not in {"", "-"}]

        lot_no = (filters.get("lot_no") or "").strip().lower()
        if lot_no:
            mapping_list = [item for item in mapping_list if lot_no in str(item.get("LotNo") or "").strip().lower()]

        def _norm_text(value):
            return "".join(str(value or "").strip().lower().split())

        if company_name:
            company_name_norm = _norm_text(company_name)
            mapping_list = [item for item in mapping_list if company_name_norm in _norm_text(item.get("CompanyName"))]

        if product_name:
            product_name_norm = product_name.lower()
            mapping_list = [
                item
                for item in mapping_list
                if (
                    product_name_norm in str(item.get("ProductName") or "").strip().lower()
                    or product_name_norm in str(item.get("SojeNo") or "").strip().lower()
                )
            ]

        return mapping_list


def get_traceability_subul_rows(filters: dict[str, str]):
    query = """
        SELECT
            CONVERT(varchar, s.ChulDate, 23) AS ChulDate,
            s.SubulNo,
            s.SeqNo,
            s.CustCode,
            ISNULL(c.CustName, '') AS CustName,
            pb.SojeNo,
            s.CodeNo,
            ISNULL(pc.CodeName, '') AS CodeName,
            s.Qty,
            ISNULL(s.LotNo, '') AS LotNo,
            ISNULL(s.InvoiceNo, '') AS InvoiceNo,
            ISNULL(s.OrderNo, '') AS OrderNo
        FROM subulinfo s
        INNER JOIN (
            SELECT DISTINCT
                LTRIM(RTRIM(PCode)) AS PCode,
                LTRIM(RTRIM(SojeNo)) AS SojeNo
            FROM dbo.ProdBom
            WHERE LTRIM(RTRIM(ISNULL(PCode, ''))) <> ''
              AND LTRIM(RTRIM(ISNULL(SojeNo, ''))) <> ''
        ) pb ON LTRIM(RTRIM(ISNULL(s.CodeNo, ''))) = pb.PCode
        LEFT JOIN dbo.Custinfo c ON c.CustCode = s.CustCode
        LEFT JOIN dbo.PCodeinfo pc ON pc.CodeNo = s.CodeNo
        WHERE CONVERT(date, s.ChulDate) BETWEEN ? AND ?
    """
    params = [filters["start_date"], filters["end_date"]]

    if filters.get("company_name"):
        query += " AND UPPER(ISNULL(c.CustName, '')) LIKE ?"
        params.append(f"%{filters['company_name'].upper()}%")

    if filters.get("product_name"):
        query += " AND (UPPER(ISNULL(pc.CodeName, '')) LIKE ? OR UPPER(ISNULL(s.CodeNo, '')) LIKE ? OR UPPER(ISNULL(pb.SojeNo, '')) LIKE ?)"
        keyword = f"%{filters['product_name'].upper()}%"
        params.extend([keyword, keyword, keyword])

    if filters.get("lot_no"):
        query += " AND UPPER(ISNULL(s.LotNo, '')) LIKE ?"
        params.append(f"%{filters['lot_no'].upper()}%")

    query += " ORDER BY s.ChulDate DESC, s.SubulNo DESC, s.SeqNo DESC"

    with get_db_connection("YUJIN_DB") as conn:
        with conn.cursor() as cursor:
            rows = fetch_dict_rows(cursor, query, params)

    results = []
    for row in rows:
        qty_value = row.get("Qty")
        try:
            qty_value = int(float(qty_value or 0))
        except (TypeError, ValueError):
            qty_value = 0

        results.append(
            {
                "ChulDate": row.get("ChulDate") or "-",
                "SubulNo": row.get("SubulNo") or "-",
                "SeqNo": row.get("SeqNo") or "-",
                "CustCode": row.get("CustCode") or "-",
                "CustName": row.get("CustName") or "-",
                "SojeNo": row.get("SojeNo") or "-",
                "CodeNo": row.get("CodeNo") or "-",
                "CodeName": row.get("CodeName") or "-",
                "Qty": qty_value,
                "QtyDisplay": format_quantity(qty_value),
                "LotNo": row.get("LotNo") or "-",
                "InvoiceNo": row.get("InvoiceNo") or "-",
                "OrderNo": row.get("OrderNo") or "-",
            }
        )

    return results


def get_subul_detail_rows(soje_no: str, lot_no: str, start_date: str, end_date: str):
    query = """
        SELECT DISTINCT
            CONVERT(varchar, s.ChulDate, 23) AS ChulDate,
            s.SubulNo,
            s.SeqNo,
            s.CustCode,
            ISNULL(c.CustName, '') AS CustName,
            s.CodeNo,
            ISNULL(pc.CodeName, '') AS CodeName,
            s.Qty,
            s.LotNo,
            s.InvoiceNo,
            s.OrderNo
        FROM subulinfo s
        LEFT JOIN dbo.Custinfo c ON c.CustCode = s.CustCode
        LEFT JOIN dbo.PCodeinfo pc ON pc.CodeNo = s.CodeNo
        WHERE CONVERT(date, s.ChulDate) BETWEEN ? AND ?
            AND CHARINDEX(
                ',' + UPPER(?) + ',',
                ',' + UPPER(REPLACE(ISNULL(s.LotNo, ''), ' ', '')) + ','
            ) > 0
            AND EXISTS (
                SELECT 1
                FROM dbo.ProdBom pb
                WHERE LTRIM(RTRIM(ISNULL(pb.PCode, ''))) = LTRIM(RTRIM(ISNULL(s.CodeNo, '')))
                  AND UPPER(LTRIM(RTRIM(ISNULL(pb.SojeNo, '')))) = UPPER(?)
            )
        ORDER BY ChulDate DESC, SubulNo DESC, SeqNo DESC
    """

    with get_db_connection("YUJIN_DB") as conn:
        with conn.cursor() as cursor:
            rows = fetch_dict_rows(cursor, query, [start_date, end_date, lot_no, soje_no])

    details = []
    for row in rows:
        qty_value = row.get("Qty")
        try:
            qty_value = int(float(qty_value or 0))
        except (TypeError, ValueError):
            qty_value = 0

        details.append(
            {
                "ChulDate": row.get("ChulDate") or "-",
                "SubulNo": row.get("SubulNo") or "-",
                "SeqNo": row.get("SeqNo") or "-",
                "CustCode": row.get("CustCode") or "-",
                "CustName": row.get("CustName") or "-",
                "CodeNo": row.get("CodeNo") or "-",
                "CodeName": row.get("CodeName") or "-",
                "Qty": qty_value,
                "QtyDisplay": format_quantity(qty_value),
                "LotNo": row.get("LotNo") or "-",
                "InvoiceNo": row.get("InvoiceNo") or "-",
                "OrderNo": row.get("OrderNo") or "-",
            }
        )

    return details


def get_heat_detail_rows(soje_no: str, lot_no: str, start_date: str, end_date: str):
    query = """
        SELECT
            CONVERT(varchar, h.MDate, 23) AS HeatDate,
            h.MTime,
            h.ETime,
            h.SilNo,
            h.SeqNo,
            ISNULL(h.Install, '') AS Install,
            ISNULL(h.Worker, '') AS Worker,
            h.CodeNo,
            ISNULL(pc.CodeName, '') AS CodeName,
            h.Qty,
            h.LotNo
        FROM HeatSilJuk h
        LEFT JOIN dbo.PCodeinfo pc ON pc.CodeNo = h.CodeNo
        WHERE UPPER(LTRIM(RTRIM(ISNULL(h.CodeNo, '')))) = UPPER(?)
            AND UPPER(REPLACE(LTRIM(RTRIM(ISNULL(h.LotNo, ''))), ' ', '')) = UPPER(REPLACE(?, ' ', ''))
            AND CONVERT(date, h.MDate) BETWEEN ? AND ?
        ORDER BY h.MDate DESC, h.SilNo DESC, h.SeqNo DESC
    """

    with get_db_connection("YUJIN_DB") as conn:
        with conn.cursor() as cursor:
            rows = fetch_dict_rows(cursor, query, [soje_no, lot_no, start_date, end_date])

    def _normalize_time(value):
        if value is None:
            return ""
        time_text = str(value).strip()
        if not time_text or time_text.lower() == "none":
            return ""
        if len(time_text) >= 8 and time_text[2] == ":" and time_text[5] == ":":
            return time_text[:5]
        if len(time_text) >= 5 and time_text[2] == ":":
            return time_text[:5]
        if time_text.isdigit() and len(time_text) >= 4:
            return f"{time_text[:2]}:{time_text[2:4]}"
        return time_text

    details = []
    for row in rows:
        qty_value = row.get("Qty")
        try:
            qty_value = int(float(qty_value or 0))
        except (TypeError, ValueError):
            qty_value = 0

        m_time = _normalize_time(row.get("MTime"))
        e_time = _normalize_time(row.get("ETime"))
        heat_time = "-"
        if m_time and e_time:
            heat_time = f"{m_time} ~ {e_time}"
        elif m_time:
            heat_time = m_time
        elif e_time:
            heat_time = e_time

        details.append(
            {
                "HeatDate": row.get("HeatDate") or "-",
                "HeatTime": heat_time,
                "SilNo": row.get("SilNo") or "-",
                "SeqNo": row.get("SeqNo") or "-",
                "Install": row.get("Install") or "-",
                "Worker": row.get("Worker") or "-",
                "CodeNo": row.get("CodeNo") or "-",
                "CodeName": row.get("CodeName") or "-",
                "Qty": qty_value,
                "QtyDisplay": format_quantity(qty_value),
                "LotNo": row.get("LotNo") or "-",
            }
        )

    return details


def get_prod_detail_rows(soje_no: str, lot_no: str, start_date: str, end_date: str):
    generated_lot_expr = """
        RIGHT(CAST(YEAR(ps.InDate) AS varchar(4)), 1)
        + CHAR(MONTH(ps.InDate) + 64)
        + RIGHT('0' + CAST(DAY(ps.InDate) AS varchar(2)), 2)
    """

    with get_db_connection("YUJIN_DB") as conn:
        with conn.cursor() as cursor:
            column_rows = fetch_dict_rows(
                cursor,
                """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'ProdSilJuk'
                """,
            )
            prod_columns = {str(row.get("COLUMN_NAME") or "").strip() for row in column_rows}

            def _pick_column(candidates):
                return next((name for name in candidates if name in prod_columns), None)

            jungja_lot_col = _pick_column(
                [
                    "JungjaLot",
                    "JungJaLot",
                    "CoreLot",
                    "CoreLotNo",
                    "JLot",
                    "JLotNo",
                    "LotNo1",
                ]
            )
            mold_code_col = _pick_column(
                [
                    "MoldCode",
                    "MoldPCode",
                    "MoldPartNo",
                    "GeumHyeongCode",
                    "GeumCode",
                    "CodeNo2",
                    "CodeNo1",
                ]
            )
            mold_name_col = _pick_column(
                [
                    "MoldName",
                    "MoldPartName",
                    "GeumHyeongName",
                    "GeumName",
                    "CodeName2",
                ]
            )

            select_jungja = f"ISNULL(ps.[{jungja_lot_col}], '') AS JungjaLot" if jungja_lot_col else "'' AS JungjaLot"
            select_mold_code = f"ISNULL(ps.[{mold_code_col}], '') AS MoldCode" if mold_code_col else "'' AS MoldCode"

            joins = ["LEFT JOIN dbo.PCodeinfo pc ON pc.CodeNo = ps.CodeNo"]
            if mold_code_col and not mold_name_col:
                joins.append(f"LEFT JOIN dbo.PCodeinfo pm ON pm.CodeNo = LTRIM(RTRIM(ISNULL(ps.[{mold_code_col}], '')))" )

            if mold_name_col:
                select_mold_name = f"ISNULL(ps.[{mold_name_col}], '') AS MoldName"
            elif mold_code_col:
                select_mold_name = "ISNULL(pm.CodeName, '') AS MoldName"
            else:
                select_mold_name = "'' AS MoldName"

            query = f"""
                SELECT
                    CONVERT(varchar, ps.InDate, 23) AS ProdDate,
                    ps.CodeNo,
                    ISNULL(pc.CodeName, '') AS CodeName,
                    ps.Qty,
                    ISNULL(ps.InGotLot, '') AS InGotLot,
                    {select_jungja},
                    {select_mold_code},
                    {select_mold_name},
                    {generated_lot_expr} AS GeneratedLot
                FROM dbo.ProdSilJuk ps
                {' '.join(joins)}
                WHERE UPPER(LTRIM(RTRIM(ISNULL(ps.CodeNo, '')))) = UPPER(?)
                    AND CONVERT(date, ps.InDate) BETWEEN ? AND ?
                    AND {generated_lot_expr} = ?
                ORDER BY ps.InDate DESC
            """

            rows = fetch_dict_rows(cursor, query, [soje_no, start_date, end_date, lot_no])

    details = []
    for row in rows:
        qty_value = row.get("Qty")
        try:
            qty_value = int(float(qty_value or 0))
        except (TypeError, ValueError):
            qty_value = 0

        details.append(
            {
                "ProdDate": row.get("ProdDate") or "-",
                "CodeNo": row.get("CodeNo") or "-",
                "CodeName": row.get("CodeName") or "-",
                "Qty": qty_value,
                "QtyDisplay": format_quantity(qty_value),
                "InGotLot": row.get("InGotLot") or "-",
                "JungjaLot": row.get("JungjaLot") or "-",
                "MoldCode": row.get("MoldCode") or "-",
                "MoldName": row.get("MoldName") or "-",
                "GeneratedLot": row.get("GeneratedLot") or "-",
            }
        )

    return details


def create_inspection(form_data, files):
    ensure_quality_inspection_columns()
    quantity_raw = (form_data.get("quantity") or "0").replace(",", "").strip()
    quantity = int(quantity_raw) if quantity_raw else 0
    bundle_count_raw = (form_data.get("bundle_count") or "0").replace(",", "").strip()
    bundle_count = int(bundle_count_raw) if bundle_count_raw else 0
    file_path = save_uploaded_file(
        files.get("file"),
        UPLOAD_DIR,
        {".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".xls", ".xlsx"},
    )
    break_file_path = save_uploaded_file(
        files.get("break_file"),
        FRACTURE_UPLOAD_DIR,
        {".pdf"},
    )

    insert_query = """
        INSERT INTO QualityInspection
        (ScreenType, InspectionDate, CompanyCode, PartNumber, Quantity, BundleCount, LotNo, Inspector, Result, DefectCount, Notes, FilePath, BreakFilePath)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    params = (
        form_data.get("screen_type") or "INGOT",
        form_data.get("inspection_date"),
        form_data.get("company_code") or None,
        form_data.get("part_number") or None,
        quantity,
        bundle_count,
        form_data.get("lot_no") or None,
        form_data.get("inspector") or None,
        form_data.get("result") or "PASS",
        0,
        form_data.get("notes") or None,
        file_path,
        break_file_path,
    )

    with get_db_connection("DB") as conn:
        with conn.cursor() as cursor:
            cursor.execute(insert_query, params)
        conn.commit()


def update_inspection(inspection_id: int, form_data, files):
    ensure_quality_inspection_columns()
    quantity_raw = (form_data.get("quantity") or "0").replace(",", "").strip()
    quantity = int(quantity_raw) if quantity_raw else 0
    bundle_count_raw = (form_data.get("bundle_count") or "0").replace(",", "").strip()
    bundle_count = int(bundle_count_raw) if bundle_count_raw else 0

    with get_db_connection("DB") as conn:
        with conn.cursor() as cursor:
            rows = fetch_dict_rows(
                cursor,
                """
                SELECT FilePath, BreakFilePath
                FROM QualityInspection
                WHERE InspectionID = ?
                """,
                [inspection_id],
            )

            if not rows:
                raise ValueError("수정할 검사 데이터가 없습니다.")

            current_row = rows[0]
            file_path = current_row.get("FilePath") or None
            break_file_path = current_row.get("BreakFilePath") or None

            if files.get("file") and files.get("file").filename:
                new_file_path = save_uploaded_file(
                    files.get("file"),
                    UPLOAD_DIR,
                    {".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".xls", ".xlsx"},
                )
                delete_uploaded_path(file_path, UPLOAD_DIR)
                file_path = new_file_path

            if files.get("break_file") and files.get("break_file").filename:
                new_break_file_path = save_uploaded_file(
                    files.get("break_file"),
                    FRACTURE_UPLOAD_DIR,
                    {".pdf"},
                )
                delete_uploaded_path(break_file_path, FRACTURE_UPLOAD_DIR)
                break_file_path = new_break_file_path

            cursor.execute(
                """
                UPDATE QualityInspection
                SET ScreenType = ?,
                    InspectionDate = ?,
                    CompanyCode = ?,
                    PartNumber = ?,
                    Quantity = ?,
                    BundleCount = ?,
                    LotNo = ?,
                    Inspector = ?,
                    Result = ?,
                    Notes = ?,
                    FilePath = ?,
                    BreakFilePath = ?
                WHERE InspectionID = ?
                """,
                [
                    form_data.get("screen_type") or "INGOT",
                    form_data.get("inspection_date"),
                    form_data.get("company_code") or None,
                    form_data.get("part_number") or None,
                    quantity,
                    bundle_count,
                    form_data.get("lot_no") or None,
                    form_data.get("inspector") or None,
                    form_data.get("result") or "PASS",
                    form_data.get("notes") or None,
                    file_path,
                    break_file_path,
                    inspection_id,
                ],
            )
        conn.commit()


def delete_uploaded_path(filename: str | None, target_dir: str):
    if not filename:
        return

    file_path = os.path.join(target_dir, filename)
    if os.path.exists(file_path):
        os.remove(file_path)


def ensure_quality_inspection_columns():
    alter_sql = """
        IF COL_LENGTH('dbo.QualityInspection', 'BundleCount') IS NULL
            ALTER TABLE dbo.QualityInspection ADD BundleCount INT NULL
    """

    with get_db_connection("DB") as conn:
        with conn.cursor() as cursor:
            cursor.execute(alter_sql)
        conn.commit()


def delete_inspection(inspection_id: int):
    with get_db_connection("DB") as conn:
        with conn.cursor() as cursor:
            rows = fetch_dict_rows(
                cursor,
                """
                SELECT FilePath, BreakFilePath
                FROM QualityInspection
                WHERE InspectionID = ?
                """,
                [inspection_id],
            )

            if not rows:
                raise ValueError("삭제할 검사 데이터가 없습니다.")

            row = rows[0]
            cursor.execute("DELETE FROM QualityInspection WHERE InspectionID = ?", [inspection_id])
        conn.commit()

    delete_uploaded_path(row.get("FilePath"), UPLOAD_DIR)
    delete_uploaded_path(row.get("BreakFilePath"), FRACTURE_UPLOAD_DIR)


def ensure_ingot_input_table():
    create_sql = """
        IF OBJECT_ID('dbo.IngotInputHistory', 'U') IS NULL
        BEGIN
            CREATE TABLE dbo.IngotInputHistory (
                InputID INT IDENTITY(1,1) PRIMARY KEY,
                BarcodeValue NVARCHAR(200) NOT NULL,
                WriterName NVARCHAR(100) NOT NULL,
                CompanyCode NVARCHAR(50) NULL,
                CompanyName NVARCHAR(200) NULL,
                PartNumber NVARCHAR(100) NULL,
                ProductName NVARCHAR(200) NULL,
                Quantity INT NULL,
                BundleCount INT NULL,
                InputAt DATETIMEOFFSET NOT NULL CONSTRAINT DF_IngotInputHistory_InputAt DEFAULT SYSDATETIMEOFFSET(),
                CreatedAt DATETIMEOFFSET NOT NULL CONSTRAINT DF_IngotInputHistory_CreatedAt DEFAULT SYSDATETIMEOFFSET()
            )
        END

        IF COL_LENGTH('dbo.IngotInputHistory', 'CompanyCode') IS NULL
            ALTER TABLE dbo.IngotInputHistory ADD CompanyCode NVARCHAR(50) NULL

        IF COL_LENGTH('dbo.IngotInputHistory', 'CompanyName') IS NULL
            ALTER TABLE dbo.IngotInputHistory ADD CompanyName NVARCHAR(200) NULL

        IF COL_LENGTH('dbo.IngotInputHistory', 'PartNumber') IS NULL
            ALTER TABLE dbo.IngotInputHistory ADD PartNumber NVARCHAR(100) NULL

        IF COL_LENGTH('dbo.IngotInputHistory', 'ProductName') IS NULL
            ALTER TABLE dbo.IngotInputHistory ADD ProductName NVARCHAR(200) NULL

        IF COL_LENGTH('dbo.IngotInputHistory', 'Quantity') IS NULL
            ALTER TABLE dbo.IngotInputHistory ADD Quantity INT NULL

        IF COL_LENGTH('dbo.IngotInputHistory', 'BundleCount') IS NULL
            ALTER TABLE dbo.IngotInputHistory ADD BundleCount INT NULL
    """

    with get_db_connection("YUJINCAST_DB") as conn:
        with conn.cursor() as cursor:
            cursor.execute(create_sql)
        conn.commit()


def get_ingot_input_entries():
    ensure_ingot_input_table()
    query = """
        SELECT
            InputID,
            BarcodeValue,
            WriterName,
            CompanyCode,
            CompanyName,
            PartNumber,
            ProductName,
            Quantity,
            BundleCount,
            CONVERT(varchar, SWITCHOFFSET(InputAt, '+09:00'), 23) AS InputDate,
            LEFT(CONVERT(varchar, SWITCHOFFSET(InputAt, '+09:00'), 108), 8) AS InputTime,
            CONVERT(varchar, SWITCHOFFSET(InputAt, '+09:00'), 120) AS InputAtText
        FROM dbo.IngotInputHistory
        ORDER BY InputID DESC
    """

    with get_db_connection("YUJINCAST_DB") as conn:
        with conn.cursor() as cursor:
            rows = fetch_dict_rows(cursor, query)

    return [
        {
            "InputID": row.get("InputID"),
            "BarcodeValue": row.get("BarcodeValue") or "-",
            "WriterName": row.get("WriterName") or "-",
            "CompanyCode": row.get("CompanyCode") or "-",
            "CompanyName": row.get("CompanyName") or "-",
            "PartNumber": row.get("PartNumber") or "-",
            "ProductName": row.get("ProductName") or "-",
            "Quantity": int(row.get("Quantity") or 0),
            "QuantityDisplay": format_quantity(row.get("Quantity") or 0),
            "BundleCount": int(row.get("BundleCount") or 0),
            "BundleCountDisplay": format_quantity(row.get("BundleCount") or 0),
            "InputDate": row.get("InputDate") or "-",
            "InputTime": row.get("InputTime") or "-",
            "InputAtText": row.get("InputAtText") or "-",
        }
        for row in rows
    ]


def resolve_ingot_source_metadata(barcode_value: str):
    company_map, product_map, _ = try_load_reference_data()
    query = """
        SELECT TOP 1
            qi.CompanyCode,
            qi.PartNumber,
            qi.Quantity,
            qi.BundleCount,
            qi.LotNo
        FROM QualityInspection qi
        WHERE LTRIM(RTRIM(ISNULL(qi.LotNo, ''))) = ?
           OR UPPER(REPLACE(REPLACE(REPLACE(ISNULL(qi.LotNo, ''), '.', ''), '-', ''), ' ', '')) = ?
        ORDER BY qi.InspectionDate DESC, qi.InspectionID DESC
    """

    normalized_lot = normalize_lot(barcode_value)
    with get_db_connection("DB") as conn:
        with conn.cursor() as cursor:
            rows = fetch_dict_rows(cursor, query, [barcode_value.strip(), normalized_lot])

    if not rows:
        return {
            "CompanyCode": None,
            "CompanyName": None,
            "PartNumber": None,
            "ProductName": None,
            "Quantity": None,
            "BundleCount": None,
        }

    row = rows[0]
    company_code = row.get("CompanyCode") or None
    part_number = row.get("PartNumber") or None
    quantity = row.get("Quantity")
    bundle_count = row.get("BundleCount")
    try:
        quantity = int(float(quantity or 0)) if quantity is not None else None
    except (TypeError, ValueError):
        quantity = None
    try:
        bundle_count = int(float(bundle_count or 0)) if bundle_count is not None else None
    except (TypeError, ValueError):
        bundle_count = None

    return {
        "CompanyCode": company_code,
        "CompanyName": company_map.get(company_code) if company_code else None,
        "PartNumber": part_number,
        "ProductName": product_map.get(part_number) if part_number else None,
        "Quantity": quantity,
        "BundleCount": bundle_count,
    }


def create_ingot_input_entry(
    writer_name: str,
    barcode_value: str,
    bundle_count: int | None = None,
    quantity_override: int | None = None,
):
    ensure_ingot_input_table()
    source_meta = resolve_ingot_source_metadata(barcode_value)
    query = """
        INSERT INTO dbo.IngotInputHistory (
            BarcodeValue,
            WriterName,
            CompanyCode,
            CompanyName,
            PartNumber,
            ProductName,
            Quantity,
            BundleCount
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """

    with get_db_connection("YUJINCAST_DB") as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                query,
                [
                    barcode_value,
                    writer_name,
                    source_meta.get("CompanyCode"),
                    source_meta.get("CompanyName"),
                    source_meta.get("PartNumber"),
                    source_meta.get("ProductName"),
                    source_meta.get("Quantity") if quantity_override is None else quantity_override,
                    source_meta.get("BundleCount") if bundle_count is None else bundle_count,
                ],
            )
        conn.commit()


def update_ingot_input_entry(entry_id: int, writer_name: str, barcode_value: str, bundle_count: int | None = None):
    ensure_ingot_input_table()
    source_meta = resolve_ingot_source_metadata(barcode_value)
    query = """
        UPDATE dbo.IngotInputHistory
        SET BarcodeValue = ?,
            WriterName = ?,
            CompanyCode = ?,
            CompanyName = ?,
            PartNumber = ?,
            ProductName = ?,
            Quantity = ?,
            BundleCount = ?,
            InputAt = SYSDATETIMEOFFSET()
        WHERE InputID = ?
    """

    with get_db_connection("YUJINCAST_DB") as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                query,
                [
                    barcode_value,
                    writer_name,
                    source_meta.get("CompanyCode"),
                    source_meta.get("CompanyName"),
                    source_meta.get("PartNumber"),
                    source_meta.get("ProductName"),
                    source_meta.get("Quantity"),
                    source_meta.get("BundleCount") if bundle_count is None else bundle_count,
                    entry_id,
                ],
            )
        conn.commit()


def delete_ingot_input_entry(entry_id: int):
    ensure_ingot_input_table()
    with get_db_connection("YUJINCAST_DB") as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM dbo.IngotInputHistory WHERE InputID = ?", [entry_id])
        conn.commit()


def clear_ingot_input_entries():
    ensure_ingot_input_table()
    with get_db_connection("YUJINCAST_DB") as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM dbo.IngotInputHistory")
        conn.commit()


def get_ingot_fifo_rows(filters: dict[str, str] | None = None):
    filters = filters or {}
    start_date = (filters.get("start_date") or "").strip()
    end_date = (filters.get("end_date") or "").strip()
    writer_name = (filters.get("writer_name") or "").strip()
    lot_no_filter = (filters.get("lot_no") or "").strip()
    _, product_map, _ = try_load_reference_data()

    inbound_rows = []
    used_rows = []

    with get_db_connection("DB") as conn:
        with conn.cursor() as cursor:
            inbound_rows = fetch_dict_rows(
                cursor,
                """
                SELECT
                    LTRIM(RTRIM(ISNULL(qi.LotNo, ''))) AS LotNo,
                    SUM(CAST(ISNULL(qi.Quantity, 0) AS float)) AS InQty,
                    SUM(CAST(ISNULL(qi.BundleCount, 0) AS float)) AS InBundleCount,
                    MAX(LTRIM(RTRIM(ISNULL(qi.PartNumber, '')))) AS PartNumber,
                    MAX(CAST(qi.InspectionDate AS date)) AS InboundDate
                FROM dbo.QualityInspection qi
                WHERE LTRIM(RTRIM(ISNULL(qi.LotNo, ''))) <> ''
                  AND ISNULL(qi.ScreenType, '') IN ('INGOT', '인고트')
                                    AND (? = '' OR CAST(qi.InspectionDate AS DATE) >= ?)
                                    AND (? = '' OR CAST(qi.InspectionDate AS DATE) <= ?)
                                    AND (? = '' OR UPPER(ISNULL(qi.LotNo, '')) LIKE UPPER(?))
                GROUP BY LTRIM(RTRIM(ISNULL(qi.LotNo, '')))
                """,
                                [start_date, start_date, end_date, end_date, lot_no_filter, f"%{lot_no_filter}%"],
            )

    ensure_ingot_input_table()
    with get_db_connection("YUJINCAST_DB") as conn:
        with conn.cursor() as cursor:
            used_rows = fetch_dict_rows(
                cursor,
                """
                SELECT
                    LTRIM(RTRIM(ISNULL(BarcodeValue, ''))) AS LotNo,
                    SUM(CAST(ISNULL(Quantity, 0) AS float)) AS UsedQty,
                    COUNT(1) AS UsedBundleCount,
                    MAX(LTRIM(RTRIM(ISNULL(ProductName, '')))) AS ProductName
                FROM dbo.IngotInputHistory
                WHERE LTRIM(RTRIM(ISNULL(BarcodeValue, ''))) <> ''
                                    AND (? = '' OR UPPER(ISNULL(BarcodeValue, '')) LIKE UPPER(?))
                GROUP BY LTRIM(RTRIM(ISNULL(BarcodeValue, '')))
                """,
                                [lot_no_filter, f"%{lot_no_filter}%"],
            )

    inbound_qty_map = {}
    inbound_bundle_map = {}
    display_lot_map = {}
    product_name_map = {}
    inbound_date_map = {}
    for row in inbound_rows:
        raw_lot = str(row.get("LotNo") or "").strip()
        norm_lot = normalize_lot(raw_lot)
        if not norm_lot:
            continue
        inbound_qty_map[norm_lot] = inbound_qty_map.get(norm_lot, 0.0) + float(row.get("InQty") or 0.0)
        inbound_bundle_map[norm_lot] = inbound_bundle_map.get(norm_lot, 0.0) + float(row.get("InBundleCount") or 0.0)
        display_lot_map.setdefault(norm_lot, raw_lot)

        part_number = str(row.get("PartNumber") or "").strip()
        mapped_product = str(product_map.get(part_number) or "").strip()
        if mapped_product:
            product_name_map.setdefault(norm_lot, mapped_product)
        elif part_number:
            product_name_map.setdefault(norm_lot, part_number)

        inbound_date = row.get("InboundDate")
        if hasattr(inbound_date, "strftime"):
            inbound_date_map.setdefault(norm_lot, inbound_date.strftime("%Y-%m-%d"))
        elif inbound_date:
            inbound_date_map.setdefault(norm_lot, str(inbound_date))

    used_bundle_map = {}
    for row in used_rows:
        raw_lot = str(row.get("LotNo") or "").strip()
        norm_lot = normalize_lot(raw_lot)
        if not norm_lot:
            continue
        used_bundle_map[norm_lot] = used_bundle_map.get(norm_lot, 0.0) + float(row.get("UsedBundleCount") or 0.0)

        used_product_name = str(row.get("ProductName") or "").strip()
        if used_product_name:
            product_name_map[norm_lot] = used_product_name

    result = []
    for norm_lot, in_qty in inbound_qty_map.items():
        in_bundle_count = inbound_bundle_map.get(norm_lot, 0.0)
        used_bundle_count = used_bundle_map.get(norm_lot, 0.0)

        if in_bundle_count > 0:
            available_bundle_count = max(0, int(round(in_bundle_count - used_bundle_count)))
            if available_bundle_count <= 0:
                continue

            qty_per_bundle = in_qty / in_bundle_count
            used_qty = qty_per_bundle * used_bundle_count
            available_qty = max(0, int(round(in_qty - used_qty)))
        else:
            available_bundle_count = 0
            available_qty = int(round(in_qty))
            if available_qty <= 0:
                continue

        lot_no = display_lot_map.get(norm_lot, norm_lot)
        product_name = product_name_map.get(norm_lot) or "-"
        inbound_date_text = inbound_date_map.get(norm_lot) or "-"
        result.append(
            {
            "InboundDate": inbound_date_text,
                "LotNo": lot_no,
                "ProductName": product_name,
                "BundleCount": available_bundle_count,
                "BundleCountDisplay": format_quantity(available_bundle_count),
                "UsedBundleCount": int(round(used_bundle_count)),
                "UsedBundleCountDisplay": format_quantity(int(round(used_bundle_count))),
                "AvailableQty": available_qty,
                "AvailableQtyDisplay": format_quantity(available_qty),
            }
        )

    result.sort(
        key=lambda row: (
            str(row.get("ProductName") or ""),
            str(row.get("InboundDate") or "9999-12-31"),
            normalize_lot(str(row.get("LotNo") or "")),
            str(row.get("LotNo") or ""),
        )
    )
    return result


def get_ingot_input_writer_options():
    fixed_writers = ["진병헌", "송무준", "허기엽", "전동출", "한형길"]
    ensure_ingot_input_table()
    with get_db_connection("YUJINCAST_DB") as conn:
        with conn.cursor() as cursor:
            rows = fetch_dict_rows(
                cursor,
                """
                SELECT DISTINCT LTRIM(RTRIM(ISNULL(WriterName, ''))) AS WriterName
                FROM dbo.IngotInputHistory
                WHERE LTRIM(RTRIM(ISNULL(WriterName, ''))) <> ''
                ORDER BY WriterName
                """,
            )

    db_writers = [str(row.get("WriterName") or "").strip() for row in rows if str(row.get("WriterName") or "").strip()]
    db_writers = [name for name in db_writers if name not in fixed_writers]
    return fixed_writers + db_writers


def find_fifo_priority_conflict(lot_no: str):
    normalized_target_lot = normalize_lot(lot_no)
    if not normalized_target_lot:
        return None

    fifo_rows = get_ingot_fifo_rows({})
    target_row = next(
        (row for row in fifo_rows if normalize_lot(str(row.get("LotNo") or "")) == normalized_target_lot),
        None,
    )
    if not target_row:
        return None

    product_name = str(target_row.get("ProductName") or "").strip()
    if not product_name:
        return None

    product_rows = [
        row
        for row in fifo_rows
        if str(row.get("ProductName") or "").strip() == product_name and int(row.get("BundleCount") or 0) > 0
    ]
    if not product_rows:
        return None

    product_rows.sort(
        key=lambda row: (
            str(row.get("InboundDate") or "9999-12-31"),
            normalize_lot(str(row.get("LotNo") or "")),
            str(row.get("LotNo") or ""),
        )
    )
    priority_row = product_rows[0]
    if normalize_lot(str(priority_row.get("LotNo") or "")) == normalized_target_lot:
        return None

    return {
        "target_row": target_row,
        "priority_row": priority_row,
    }


@app.route("/")
def index():
    start_date, end_date = get_default_dates()
    default_inspection_date = datetime.now().strftime("%Y-%m-%d")
    filters = {
        "start_date": request.args.get("start_date", start_date),
        "end_date": request.args.get("end_date", end_date),
        "company_name": request.args.get("company_name", "").strip(),
        "product_name": request.args.get("product_name", "").strip(),
        "lot_no": request.args.get("lot_no", "").strip(),
    }
    companies = load_form_options()
    company_lookup = {company["CustCode"]: company["CustName"] for company in companies}
    inspections = []
    error = None
    notice = request.args.get("notice", "")

    try:
        inspections = get_inspections(filters)
    except Exception as exc:
        error = str(exc)

    return render_template(
        "index.html",
        inspections=inspections,
        filters=filters,
        error=error,
        notice=notice,
        companies=companies,
        company_lookup=company_lookup,
        default_inspection_date=default_inspection_date,
    )


@app.route("/ingot/traceability")
def ingot_traceability():
    today = datetime.now()
    start_date = request.args.get("start_date", (today - timedelta(days=30)).strftime("%Y-%m-%d"))
    end_date = request.args.get("end_date", today.strftime("%Y-%m-%d"))
    filters = {
        "start_date": start_date,
        "end_date": end_date,
        "lotno_only": request.args.get("lotno_only", "0") == "1",
        "company_name": request.args.get("company_name", "").strip(),
        "product_name": request.args.get("product_name", "").strip(),
        "lot_no": request.args.get("lot_no", "").strip(),
    }
    mapping_list = []
    error = None

    try:
        mapping_list = get_traceability_mappings(filters)
    except Exception as exc:
        error = str(exc)

    return render_template(
        "ingot_traceability.html",
        mapping_list=mapping_list,
        total_count=len(mapping_list),
        filters=filters,
        error=error,
    )


@app.route("/ingot/traceability/subul")
def ingot_traceability_subul():
    today = datetime.now()
    start_date = request.args.get("start_date", (today - timedelta(days=30)).strftime("%Y-%m-%d"))
    end_date = request.args.get("end_date", today.strftime("%Y-%m-%d"))
    filters = {
        "start_date": start_date,
        "end_date": end_date,
        "company_name": request.args.get("company_name", "").strip(),
        "product_name": request.args.get("product_name", "").strip(),
        "lot_no": request.args.get("lot_no", "").strip(),
    }
    subul_rows = []
    error = None

    try:
        subul_rows = get_traceability_subul_rows(filters)
    except Exception as exc:
        error = str(exc)

    return render_template(
        "ingot_traceability_subul.html",
        subul_rows=subul_rows,
        total_count=len(subul_rows),
        filters=filters,
        error=error,
    )


@app.route("/ingot/input")
def ingot_input():
    return render_template("ingot_input.html")


@app.route("/ingot/fifo")
def ingot_fifo():
    start_date, end_date = get_default_dates()
    recent_lot = request.args.get("recent_lot", "").strip()
    status_kind = request.args.get("status_kind", "").strip()
    filters = {
        "writer_name": request.args.get("writer_name", "").strip(),
        "lot_no": request.args.get("lot_no", "").strip(),
        "start_date": request.args.get("start_date", start_date),
        "end_date": request.args.get("end_date", end_date),
    }

    page_text = request.args.get("page", "1").strip()
    try:
        page = max(1, int(page_text))
    except ValueError:
        page = 1

    per_page = 5
    fifo_rows = []
    writer_options = []
    page_rows = []
    total_count = 0
    total_pages = 1
    error = (request.args.get("error") or "").strip() or None
    notice = (request.args.get("notice") or "").strip() or None
    recent_status = None
    try:
        writer_options = get_ingot_input_writer_options()
        fifo_rows = get_ingot_fifo_rows(filters)
        total_count = len(fifo_rows)
        if status_kind:
            recent_status = {
                "kind": status_kind,
                "label": request.args.get("status_label", "").strip() or "상태",
                "lot_no": request.args.get("status_lot", "").strip() or recent_lot,
                "bundle_text": request.args.get("status_bundle_text", "").strip() or "0",
                "detail_text": request.args.get("status_detail", "").strip() or "",
                "extra_text": request.args.get("status_extra", "").strip() or "",
            }
        elif recent_lot:
            normalized_recent_lot = normalize_lot(recent_lot)
            matched_row = next(
                (row for row in fifo_rows if normalize_lot(str(row.get("LotNo") or "")) == normalized_recent_lot),
                None,
            )
            if matched_row:
                recent_status = {
                    "kind": "available",
                    "label": "사용 가능",
                    "lot_no": matched_row.get("LotNo") or recent_lot,
                    "bundle_text": matched_row.get("BundleCountDisplay") or "0",
                    "detail_text": "",
                    "extra_text": "",
                }
            else:
                recent_status = {
                    "kind": "done",
                    "label": "사용 완료",
                    "lot_no": recent_lot,
                    "bundle_text": "0",
                    "detail_text": "",
                    "extra_text": "",
                }
        total_pages = max(1, (total_count + per_page - 1) // per_page)
        if page > total_pages:
            page = total_pages
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_rows = fifo_rows[start_idx:end_idx]
    except Exception as exc:
        error = str(exc)

    return render_template(
        "ingot_fifo.html",
        fifo_rows=page_rows,
        writer_options=writer_options,
        total_count=total_count,
        filters=filters,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        error=error,
        notice=notice,
        recent_status=recent_status,
    )


@app.post("/ingot/fifo/quick-input")
def ingot_fifo_quick_input():
    writer_name = str(request.form.get("writer_name") or "").strip()
    lot_no = str(request.form.get("lot_no") or "").strip()
    start_date = str(request.form.get("start_date") or "").strip()
    end_date = str(request.form.get("end_date") or "").strip()

    redirect_params = {
        "writer_name": writer_name,
        "start_date": start_date,
        "end_date": end_date,
    }

    if not writer_name:
        return redirect(url_for("ingot_fifo", **redirect_params, error="작성자를 먼저 선택하세요."))

    if not lot_no:
        return redirect(url_for("ingot_fifo", **redirect_params, error="LOT No를 입력하세요."))

    try:
        normalized_lot = normalize_lot(lot_no)
        available_rows = get_ingot_fifo_rows({})
        matched_available_row = next(
            (row for row in available_rows if normalize_lot(str(row.get("LotNo") or "")) == normalized_lot),
            None,
        )
        if not matched_available_row:
            return redirect(
                url_for(
                    "ingot_fifo",
                    **redirect_params,
                    status_kind="blocked",
                    status_label="사용 불가 LOT",
                    status_detail="사용가능한 lot no가 아닙니다 관리자에게 문의하세요",
                    status_lot=lot_no,
                    status_bundle_text="0",
                )
            )

        conflict = find_fifo_priority_conflict(lot_no)
        if conflict:
            priority_row = conflict["priority_row"]
            return redirect(
                url_for(
                    "ingot_fifo",
                    **redirect_params,
                    status_kind="blocked",
                    status_label="사용 불가 LOT",
                    status_detail="먼저 사용해야 할 LOT",
                    status_lot=str(priority_row.get("LotNo") or ""),
                    status_bundle_text=str(priority_row.get("BundleCountDisplay") or "0"),
                    status_extra=str(priority_row.get("ProductName") or ""),
                )
            )

        # FIFO quick input treats each lot scan as one used bundle.
        source_meta = resolve_ingot_source_metadata(lot_no)
        total_quantity = source_meta.get("Quantity")
        total_bundle_count = source_meta.get("BundleCount")
        quantity_per_bundle = None

        if total_quantity not in [None, ""] and total_bundle_count not in [None, "", 0]:
            quantity_per_bundle = max(1, int(round(float(total_quantity) / float(total_bundle_count))))

        create_ingot_input_entry(writer_name, lot_no, 1, quantity_per_bundle)
    except Exception as exc:
        return redirect(url_for("ingot_fifo", **redirect_params, error=str(exc)))

    return redirect(url_for("ingot_fifo", **redirect_params, notice="입력 완료", recent_lot=lot_no))


@app.get("/api/ingot-input/entries")
def api_ingot_input_entries():
    try:
        return jsonify({"success": True, "rows": get_ingot_input_entries()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc), "rows": []}), 500


@app.post("/api/ingot-input/entries")
def api_create_ingot_input_entry():
    payload = request.get_json(silent=True) or request.form
    writer_name = str(payload.get("writer_name") or "").strip()
    barcode_value = str(payload.get("barcode_value") or "").strip()
    bundle_count_raw = str(payload.get("bundle_count") or "").strip()

    if not writer_name:
        return jsonify({"success": False, "error": "작성자는 필수입니다."}), 400
    if not barcode_value:
        return jsonify({"success": False, "error": "바코드는 필수입니다."}), 400

    try:
        bundle_count = int(bundle_count_raw) if bundle_count_raw != "" else None
    except ValueError:
        return jsonify({"success": False, "error": "번들수는 숫자여야 합니다."}), 400

    try:
        create_ingot_input_entry(writer_name, barcode_value, bundle_count)
        return jsonify({"success": True, "rows": get_ingot_input_entries()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.post("/api/ingot-input/entries/<int:entry_id>/update")
def api_update_ingot_input_entry(entry_id: int):
    payload = request.get_json(silent=True) or request.form
    writer_name = str(payload.get("writer_name") or "").strip()
    barcode_value = str(payload.get("barcode_value") or "").strip()
    bundle_count_raw = str(payload.get("bundle_count") or "").strip()

    if not writer_name:
        return jsonify({"success": False, "error": "작성자는 필수입니다."}), 400
    if not barcode_value:
        return jsonify({"success": False, "error": "바코드는 필수입니다."}), 400

    try:
        bundle_count = int(bundle_count_raw) if bundle_count_raw != "" else None
    except ValueError:
        return jsonify({"success": False, "error": "번들수는 숫자여야 합니다."}), 400

    try:
        update_ingot_input_entry(entry_id, writer_name, barcode_value, bundle_count)
        return jsonify({"success": True, "rows": get_ingot_input_entries()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.post("/api/ingot-input/entries/clear")
def api_clear_ingot_input_entries():
    try:
        clear_ingot_input_entries()
        return jsonify({"success": True, "rows": []})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.post("/api/ingot-input/entries/<int:entry_id>/delete")
def api_delete_ingot_input_entry(entry_id: int):
    try:
        delete_ingot_input_entry(entry_id)
        return jsonify({"success": True, "rows": get_ingot_input_entries()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500


@app.get("/api/traceability/mappings")
def api_traceability_mappings():
    today = datetime.now()
    filters = {
        "start_date": (request.args.get("start_date") or (today - timedelta(days=30)).strftime("%Y-%m-%d")).strip(),
        "end_date": (request.args.get("end_date") or today.strftime("%Y-%m-%d")).strip(),
        "lotno_only": request.args.get("lotno_only", "0") == "1",
        "company_name": (request.args.get("company_name") or "").strip(),
        "product_name": (request.args.get("product_name") or "").strip(),
        "lot_no": (request.args.get("lot_no") or "").strip(),
    }

    try:
        mapping_list = get_traceability_mappings(filters)
        return jsonify(
            {
                "success": True,
                "filters": filters,
                "rows": mapping_list,
                "total_count": len(mapping_list),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc), "rows": [], "total_count": 0}), 500


@app.post("/inspection/new")
def new_inspection():
    try:
        create_inspection(request.form, request.files)
        return redirect(url_for("index", notice="created"))
    except Exception as exc:
        return redirect(url_for("index", notice=f"error:{exc}"))


@app.post("/inspection/update/<int:inspection_id>")
def update_inspection_route(inspection_id: int):
    try:
        update_inspection(inspection_id, request.form, request.files)
        return redirect(url_for("index", notice="updated"))
    except Exception as exc:
        return redirect(url_for("index", notice=f"error:{exc}"))


@app.post("/inspection/delete/<int:inspection_id>")
def remove_inspection(inspection_id: int):
    try:
        delete_inspection(inspection_id)
        return redirect(url_for("index", notice="deleted"))
    except Exception as exc:
        return redirect(url_for("index", notice=f"error:{exc}"))


@app.get("/api/traceability/subul-details")
def api_traceability_subul_details():
    soje_no = (request.args.get("soje_no") or "").strip()
    lot_no = (request.args.get("lot_no") or "").strip()
    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()

    if not soje_no or not lot_no:
        return jsonify({"success": False, "error": "soje_no와 lot_no는 필수입니다.", "rows": []}), 400

    today = datetime.now()
    if not start_date:
        start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = today.strftime("%Y-%m-%d")

    try:
        rows = get_subul_detail_rows(soje_no, lot_no, start_date, end_date)
        return jsonify(
            {
                "success": True,
                "soje_no": soje_no,
                "lot_no": lot_no,
                "start_date": start_date,
                "end_date": end_date,
                "rows": rows,
                "total_count": len(rows),
                "total_qty": int(sum(row.get("Qty") or 0 for row in rows)),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc), "rows": []}), 500


@app.get("/api/traceability/heat-details")
def api_traceability_heat_details():
    soje_no = (request.args.get("soje_no") or "").strip()
    lot_no = (request.args.get("lot_no") or "").strip()
    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()

    if not soje_no or not lot_no:
        return jsonify({"success": False, "error": "soje_no와 lot_no는 필수입니다.", "rows": []}), 400

    today = datetime.now()
    if not start_date:
        start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = today.strftime("%Y-%m-%d")

    try:
        rows = get_heat_detail_rows(soje_no, lot_no, start_date, end_date)
        return jsonify(
            {
                "success": True,
                "soje_no": soje_no,
                "lot_no": lot_no,
                "start_date": start_date,
                "end_date": end_date,
                "rows": rows,
                "total_count": len(rows),
                "total_qty": int(sum(row.get("Qty") or 0 for row in rows)),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc), "rows": []}), 500


@app.get("/api/traceability/prod-details")
def api_traceability_prod_details():
    soje_no = (request.args.get("soje_no") or "").strip()
    lot_no = (request.args.get("lot_no") or "").strip()
    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()

    if not soje_no or not lot_no:
        return jsonify({"success": False, "error": "soje_no와 lot_no는 필수입니다.", "rows": []}), 400

    today = datetime.now()
    if not start_date:
        start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    if not end_date:
        end_date = today.strftime("%Y-%m-%d")

    try:
        rows = get_prod_detail_rows(soje_no, lot_no, start_date, end_date)
        return jsonify(
            {
                "success": True,
                "soje_no": soje_no,
                "lot_no": lot_no,
                "start_date": start_date,
                "end_date": end_date,
                "rows": rows,
                "total_count": len(rows),
                "total_qty": int(sum(row.get("Qty") or 0 for row in rows)),
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc), "rows": []}), 500


@app.get("/api/products")
def api_products():
    company_code = request.args.get("company_code", "").strip()
    if not company_code:
        return {"success": False, "error": "company_code is required", "products": []}, 400

    try:
        products = load_products_by_company(company_code)
        return {"success": True, "products": products}
    except Exception as exc:
        return {"success": False, "error": str(exc), "products": []}, 500


if __name__ == "__main__":
    debug_mode = os.getenv("DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}
    port = int(os.getenv("PORT", "5002"))
    app.run(debug=debug_mode, host="0.0.0.0", port=port)
