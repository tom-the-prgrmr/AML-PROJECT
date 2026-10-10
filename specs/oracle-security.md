---
id: oracle-security
status: approved
approved_by: pthieu
---

# Phase 2b — Bảo mật Oracle: roles least privilege, masking view PII, unified auditing, `audit_log` append-only

## Bối cảnh
Spec 2b của Phase 2 (PROJECT_BRIEF.md mục 3, gạch đầu dòng **Security**; cách tách 2a/2b/2c/2d đã chốt ở
`specs/oracle-schema-core.md` Q1, Q14). Hiện mọi thứ chạy bằng một user duy nhất `aml_owner` (APP_USER của image
gvenzl, có `DB_DEVELOPER_ROLE`), chưa có role, chưa có masking, chưa bật audit policy nào
(`audit_unified_enabled_policies` rỗng), và `audit_log` chỉ "append-only" trên giấy — comment trong
`sql/oracle/ddl/000_audit_log.sql` hứa trigger + grants ở Phase 2. 2b thêm: 4 role tách biệt
(`aml_app`, `aml_analyst`, `aml_graph_sync`, `aml_auditor`) với quyền tối thiểu, view `customers_masked` che một
phần tên/số giấy tờ/điện thoại/email cho analyst, 2 unified audit policy cho truy cập bảng nhạy cảm, và trigger
chặn UPDATE/DELETE/TRUNCATE trên `audit_log`. Logic che được viết một lần bằng Python (tham chiếu) và hai lần bằng
SQL (Oracle, DuckDB), test đối chiếu để chế độ DuckDB-only vẫn kiểm được masking.

Đã kiểm tra trên instance đang chạy (Oracle 23.26.3 Free, `FREEPDB1`, chỉ đọc): `v$option 'Unified Auditing' = TRUE`;
`AUDIT_ADMIN`/`AUDIT_VIEWER` tồn tại nhưng chỉ cấp cho `SYS`; `SYSTEM` có `CREATE ROLE`, `CREATE USER`,
`GRANT ANY ROLE`, `AUDIT SYSTEM`, `AUDIT ANY`; `aml_owner` **không** có `CREATE ROLE`/`CREATE USER` nhưng có
`CREATE VIEW`, `CREATE TRIGGER`; charset `AL32UTF8`.

### Interface đề xuất (để test gọi trực tiếp)
```python
# src/aml/dba/masking.py — cài đặt tham chiếu, thuần Python, không cần DB
MASKED_COLUMNS: tuple[str, ...] = (
    "cif",
    "full_name",
    "gender",
    "birth_year",
    "nationality",
    "occupation",
    "kyc_risk",
    "id_type",
    "id_number",
    "phone",
    "email",
    "address_format",
    "ward",
    "district",
    "province",
)


def mask_name(value: str | None) -> str | None: ...
def mask_id(value: str | None) -> str | None: ...
def mask_phone(value: str | None) -> str | None: ...
def mask_email(value: str | None) -> str | None: ...
def mask_customers(
    customers: pd.DataFrame,
) -> pd.DataFrame: ...  # cột = MASKED_COLUMNS, cùng số dòng


# src/aml/dba/security.py
ROLES: tuple[str, ...] = ("aml_app", "aml_analyst", "aml_graph_sync", "aml_auditor")
DEMO_USERS: dict[str, str] = {role: f"{role}_usr" for role in ROLES}  # role -> user đăng nhập
AUDIT_POLICIES: tuple[str, ...] = ("aml_pii_access", "aml_audit_log_tamper")
ROLE_GRANTS: dict[str, frozenset[tuple[str, str]]]  # role -> {(privilege, object)}, xem bảng dưới


class SecurityConfigError(RuntimeError): ...  # thiếu/sai secret; thông điệp nêu tên biến .env


def apply_security(settings: Settings) -> dict[str, list[str]]: ...  # Oracle only, idempotent
```
- `apply_security` trả `{"roles": [...], "users": [...], "policies": [...]}`; trên backend khác Oracle raise
  `NotImplementedError("... Oracle only ...")`. Thứ tự: (1) kết nối **admin** (`db.oracle.admin_user`, mặc định
  `system`) chạy `security/010_roles_users.sql` + tạo/đồng bộ mật khẩu 4 user demo; (2) kết nối **owner** chạy
  `apply_schema` (để có view + trigger) rồi `security/020_grants.sql`; (3) kết nối admin với
  `ALTER SESSION SET CURRENT_SCHEMA = <owner>` chạy `security/030_audit_policies.sql`; (4) ghi 1 dòng `audit_log`.
- Config: `OracleConfig` thêm `admin_user: str = "system"`, `admin_password: str = ""`, `demo_password: str = ""`;
  `SECRET_ENV_MAP` thêm `ORACLE_SYS_PASSWORD -> db.oracle.admin_password` (biến đã có trong `.env`, dùng chung với
  docker-compose) và `ORACLE_DEMO_PASSWORD -> db.oracle.demo_password` (biến mới, thêm vào `.env.example`).
  Không mật khẩu nào nằm trong `config.yaml` hay file `.sql`; lệnh `CREATE/ALTER USER ... IDENTIFIED BY` do Python
  dựng, từ chối mật khẩu rỗng hoặc chứa `"`.
- `SCHEMA_SCRIPTS` thêm `"ddl/050_security_objects.sql"` (Oracle: view `customers_masked` + 2 trigger) và
  `"ddl/050_customers_masked.sql"` (DuckDB: chỉ view). Các script `security/*.sql` **không** nằm trong
  `SCHEMA_SCRIPTS` (cần role tồn tại / quyền admin).
- CLI mới `aml security-setup` gọi `apply_security(get_settings())` và in roles/users/policies.
- Test đăng nhập bằng user demo qua `load_settings(environ={..., "ORACLE_APP_USER": "aml_analyst_usr",
  "ORACLE_APP_PASSWORD": <demo_password>})` + `OracleDb(settings)`; truy cập đối tượng bằng tên đầy đủ
  `aml_owner.<object>` (không tạo synonym).

### Quy tắc che (xác nhận ở Câu hỏi mở)
`NULL` → `NULL` cho mọi hàm; chuỗi rỗng/chỉ khoảng trắng → `None` (khớp Oracle coi `''` là `NULL`).
- `mask_name`: tách theo khoảng trắng; giữ nguyên token đầu (họ), mỗi token sau → ký tự đầu + `.`; nối bằng một
  dấu cách. Chỉ một token → ký tự đầu + `.`.
- `mask_id`: giữ 4 ký tự cuối, phần trước thay bằng `*` cùng độ dài; độ dài ≤ 4 → toàn `*`.
- `mask_phone`: bỏ mọi ký tự không phải chữ số, giữ 3 chữ số cuối, phần trước thay bằng `*`; ≤ 3 chữ số → toàn `*`;
  không có chữ số nào → `None`.
- `mask_email`: có `@` và phần trước `@` đầu tiên khác rỗng → ký tự đầu + `***@` + phần sau `@`; còn lại → `***`.
- View `customers_masked` có đúng các cột `MASKED_COLUMNS` theo thứ tự đó: `full_name`, `id_number`, `phone`,
  `email` đã che; `birth_year` = năm của `dob` (số nguyên, thay cho `dob`); **không có** `dob`, `street`,
  `address`, `device_id`, `ip`; các cột còn lại giữ nguyên.

### Ma trận quyền (`ROLE_GRANTS`, đối tượng thuộc schema owner; xác nhận ở Câu hỏi mở)
| Role | Quyền đối tượng | Khác |
|---|---|---|
| `aml_app` | `SELECT` trên `customers`, `customer_person`, `admin_unit_mapping`, `accounts`, `transactions`, `watchlist`, `watchlist_alias`, `acct_edge_daily`, `customers_masked`; `INSERT` trên `audit_log` | — |
| `aml_analyst` | `SELECT` trên `customers_masked`, `accounts`, `transactions`, `acct_edge_daily`, `watchlist`, `watchlist_alias`, `admin_unit_mapping` | — |
| `aml_graph_sync` | `SELECT` trên `customers_masked`, `accounts`, `transactions`, `acct_edge_daily` | — |
| `aml_auditor` | `SELECT` trên `audit_log` | được cấp role `AUDIT_VIEWER` |

Không role nào có system privilege; mỗi user demo chỉ có `CREATE SESSION` + đúng một role; không role nào thấy
`ground_truth`, `dq_labels`.

### Thiết kế đối tượng Oracle
- `TRG_AUDIT_LOG_APPEND_ONLY`: `BEFORE UPDATE OR DELETE ON audit_log` mức **statement** →
  `RAISE_APPLICATION_ERROR(-20100, 'audit_log is append-only')` (chặn cả owner, cả câu lệnh khớp 0 dòng).
- `TRG_AUDIT_LOG_NO_TRUNCATE`: `BEFORE TRUNCATE ON SCHEMA`, nếu `ora_dict_obj_name = 'AUDIT_LOG'` →
  `RAISE_APPLICATION_ERROR(-20101, 'audit_log is append-only')`.
- Policy `AML_PII_ACCESS`: `ACTIONS SELECT, INSERT, UPDATE, DELETE` trên `customers` và `customer_person`, `SELECT`
  trên `customers_masked`. Policy `AML_AUDIT_LOG_TAMPER`: `ACTIONS UPDATE, DELETE` trên `audit_log`. Cả hai bật bằng
  `AUDIT POLICY <tên>` cho mọi user (kể cả owner), cả thành công lẫn thất bại.
- Mọi DDL nằm trong khối PL/SQL `EXECUTE IMMEDIATE` (kể cả `CREATE OR REPLACE VIEW/TRIGGER`, để không vi phạm AC1
  của 2a), nuốt đúng mã "đã tồn tại" (ORA-01921 role, ORA-46358 policy); mỗi statement kết thúc bằng dòng `/`.

## Tiêu chí nghiệm thu
<!-- Fixture TINY = `tiny_parquet` của tests/datagen/conftest.py. Test có nhãn [oracle] dùng @pytest.mark.oracle
(tự skip khi Oracle không chạy) và skip thêm với thông điệp nêu tên biến nếu thiếu ORACLE_SYS_PASSWORD hoặc
ORACLE_DEMO_PASSWORD; fixture của chúng gọi `apply_security` trước. Các AC còn lại chạy ở chế độ DuckDB-only. -->
- AC1: Given các hàm trong `aml.dba.masking`, When gọi với giá trị mẫu, Then `mask_name("Nguyễn Thanh Đạt") == "Nguyễn T. Đ."`, `mask_name("  Vũ Thị   Phương Anh ") == "Vũ T. P. A."`, `mask_name("Madonna") == "M."`; `mask_id("032084621159") == "********1159"`, `mask_id("486421276") == "*****1276"`, `mask_id("1234") == "****"`; `mask_phone("085.250.0337") == "*******337"`, `mask_phone("+84 912 345 678") == "********678"`, `mask_phone("12") == "**"`, `mask_phone("n/a") is None`; `mask_email("datn5493@icloud.com") == "d***@icloud.com"`, `mask_email("khong-co-a-cong") == "***"`, `mask_email("@x.com") == "***"`; và cả 4 hàm trả `None` cho `None`, `""` và `"   "`.
- AC2: Given DuckDB rỗng (`duck`) và fixture TINY đã nạp bằng `load_parquet`, When đọc `SELECT * FROM customers_masked ORDER BY cif`, Then danh sách cột == `list(MASKED_COLUMNS)`, số dòng = 300, DataFrame bằng `mask_customers(customers)` (đọc từ `customers.parquet`, sắp theo `cif`, `birth_year` về `Int64`) theo `pd.testing.assert_frame_equal`, và không giá trị `id_number` hay `phone` gốc nào (khác null) của `customers` xuất hiện trong cột tương ứng của view.
- AC3: Given repo (không cần Oracle), When kiểm tra tĩnh, Then `security/010_roles_users.sql`, `security/020_grants.sql`, `security/030_audit_policies.sql` resolve qua `sql_file(name, "oracle")` và `split_oracle_script` tách mỗi file ra ≥ 1 statement không lỗi; `SCHEMA_SCRIPTS["oracle"][-1] == "ddl/050_security_objects.sql"` và `SCHEMA_SCRIPTS["duckdb"][-1] == "ddl/050_customers_masked.sql"`; không file nào dưới `sql/` chứa chuỗi `IDENTIFIED BY`; `load_settings(environ={})` cho `db.oracle.admin_user == "system"`, `admin_password == ""`, `demo_password == ""`; và `load_settings(environ={"ORACLE_SYS_PASSWORD": "s1", "ORACLE_DEMO_PASSWORD": "d1"})` cho `admin_password == "s1"`, `demo_password == "d1"`.
- AC4: Given `DB_BACKEND=duckdb`, When chạy `aml security-setup`, Then exit code 2 và stderr chứa "Oracle only"; Given `DB_BACKEND=oracle` nhưng `ORACLE_SYS_PASSWORD` rỗng, Then exit code 2, stderr chứa `ORACLE_SYS_PASSWORD`; Given `ORACLE_DEMO_PASSWORD` rỗng hoặc bằng `a"b`, Then exit code 2, stderr chứa `ORACLE_DEMO_PASSWORD`; trong cả ba trường hợp không mở kết nối Oracle nào (kiểm bằng monkeypatch `oracledb.connect` raise nếu bị gọi).
- AC5: [oracle] Given Oracle đang chạy với đủ secret, When gọi `apply_security(settings)` hai lần liên tiếp, Then cả hai lần không raise và trả `{"roles": ["aml_app", "aml_analyst", "aml_graph_sync", "aml_auditor"], "users": ["aml_app_usr", "aml_analyst_usr", "aml_graph_sync_usr", "aml_auditor_usr"], "policies": ["aml_pii_access", "aml_audit_log_tamper"]}`; `dba_roles` có đủ 4 role, `dba_users` có đủ 4 user với `account_status = 'OPEN'`, `audit_unified_enabled_policies` có đúng 2 policy tên bắt đầu bằng `AML_`; đăng nhập được bằng cả 4 user với `demo_password`; và `audit_log` có đúng 2 dòng mới `module='dba'`, `entity_type='security'`, `decision='SECURITY_APPLIED'` với `details.roles` gồm 4 tên role.
- AC6: [oracle] Given sau `apply_security`, When đọc data dictionary bằng kết nối admin, Then với mỗi role, tập `(privilege, table_name)` trong `dba_tab_privs` (`grantee` = role, `owner` = owner) bằng đúng `ROLE_GRANTS[role]` (lần lượt 10, 7, 4, 1 quyền như bảng ma trận); `dba_sys_privs` không có dòng nào cho 4 role; `dba_role_privs` của `AML_AUDITOR` = {`AUDIT_VIEWER`} và của 3 role còn lại rỗng; mỗi user demo có `dba_sys_privs` = {`CREATE SESSION`}, `dba_role_privs` = đúng một role tương ứng, và không có dòng nào trong `dba_tab_privs`.
- AC7: [oracle] Given fixture TINY đã nạp và `apply_security`, When từng user demo chạy câu lệnh trên `aml_owner.<object>`, Then: `aml_analyst_usr` `SELECT COUNT(*) FROM customers_masked` = 300 nhưng `SELECT` trên `customers`, `customer_person`, `ground_truth`, `audit_log` raise lỗi chứa `ORA-00942`; `aml_graph_sync_usr` `SELECT COUNT(*) FROM acct_edge_daily` thành công nhưng `INSERT`/`UPDATE`/`DELETE` trên `transactions` raise lỗi chứa `ORA-01031`/`ORA-41900` và `SELECT` trên `customers` raise `ORA-00942`; `aml_app_usr` `SELECT COUNT(*) FROM customers` = 300 và `INSERT` một dòng vào `audit_log` thành công nhưng `SELECT` trên `audit_log` raise `ORA-01031`/`ORA-41900` và `DELETE FROM customers` raise `ORA-01031`/`ORA-41900`; `aml_auditor_usr` `SELECT COUNT(*) FROM audit_log` ≥ 1 nhưng `INSERT` vào `audit_log` raise `ORA-01031`/`ORA-41900` và `SELECT` trên `customers_masked`, `transactions` raise `ORA-00942`.
- AC8: [oracle] Given `audit_log` có N ≥ 1 dòng sau `apply_schema`, When kết nối owner chạy `UPDATE audit_log SET reason = 'x'`, `DELETE FROM audit_log`, `DELETE FROM audit_log WHERE 1 = 0`, và `aml_app_usr` chạy `UPDATE aml_owner.audit_log SET reason = 'x'`, Then ba câu của owner raise lỗi chứa `ORA-20100` và `audit_log is append-only`, câu của `aml_app_usr` raise `ORA-01031`/`ORA-41900`; `TRUNCATE TABLE audit_log` (owner) raise lỗi chứa `ORA-20101`; `COUNT(*)` vẫn = N; sau đó một lệnh `audit()` hợp lệ vẫn ghi được (COUNT = N + 1); và `user_triggers` có `TRG_AUDIT_LOG_APPEND_ONLY`, `TRG_AUDIT_LOG_NO_TRUNCATE` với `status = 'ENABLED'`.
- AC9: [oracle] Given `apply_security` đã chạy và đếm trước số dòng `unified_audit_trail` theo từng bộ lọc dưới đây, When `aml_analyst_usr` chạy `SELECT COUNT(*) FROM aml_owner.customers_masked`, owner chạy `SELECT COUNT(*) FROM customers` và `DELETE FROM audit_log` (bị trigger chặn), rồi `aml_auditor_usr` đọc `unified_audit_trail`, Then số dòng tăng ≥ 1 cho mỗi bộ lọc: (`dbusername='AML_ANALYST_USR'`, `action_name='SELECT'`, `object_name='CUSTOMERS_MASKED'`, `unified_audit_policies` chứa `AML_PII_ACCESS`, `return_code=0`); (`dbusername` = owner viết hoa, `action_name='SELECT'`, `object_name='CUSTOMERS'`, chứa `AML_PII_ACCESS`); (`dbusername` = owner, `action_name='DELETE'`, `object_name='AUDIT_LOG'`, chứa `AML_AUDIT_LOG_TAMPER`, `return_code=20100`); còn `aml_analyst_usr` đọc `unified_audit_trail` thì raise lỗi chứa `ORA-00942`.
- AC10: [oracle] Given fixture TINY đã nạp vào Oracle bằng `load_parquet`, When owner đọc `SELECT * FROM customers_masked ORDER BY cif`, Then tên cột (viết thường) == `list(MASKED_COLUMNS)`, số dòng = 300 và DataFrame bằng `mask_customers(customers)` (cùng chuẩn hoá như AC2) theo `pd.testing.assert_frame_equal` — tức Oracle, DuckDB và Python cho cùng kết quả che, kể cả tên tiếng Việt có dấu.

## Ngoài phạm vi
- Chuyển kết nối runtime của ứng dụng/CLI từ `aml_owner` sang `aml_app_usr`; API Phase 9 đọc `customers_masked` theo role (Phase 9); Neo4j sync dùng `aml_graph_sync_usr` (Phase 5).
- Che PII trong `transactions` (`counterparty_name`, `memo`, `device_id`, `ip`), `customer_person.variations`, `watchlist`; Oracle Data Redaction (`DBMS_REDACT`), VPD/row-level security, TDE, Database Vault.
- Trigger/role/unified auditing trên DuckDB (DuckDB chỉ có view `customers_masked`); append-only trên DuckDB.
- Chặn `DROP TABLE audit_log`, `ALTER TABLE ... DISABLE TRIGGER` của owner; tách owner khỏi quyền DDL; bảng blockchain/immutable.
- Partition `audit_log`, purge/archive, dọn `unified_audit_trail` bằng `DBMS_AUDIT_MGMT` (2c); ghi chú vận hành audit trong `dba/RUNBOOK.md` (2d).
- Script init của container (`docker/oracle/init`), password profile/verify function, xoay vòng mật khẩu, wallet/vault; lệnh gỡ (`drop role/user/policy`).
- Quyền trên bảng của các phase sau (alerts, cases, dq_*): mỗi phase tự bổ sung vào `ROLE_GRANTS` và `020_grants.sql`.

## Giả định
- `SYSTEM` (mật khẩu = `ORACLE_SYS_PASSWORD` của image gvenzl) đăng nhập được vào `FREEPDB1` không cần `SYSDBA`, và các privilege `CREATE ROLE`, `CREATE USER`, `GRANT ANY ROLE`, `AUDIT SYSTEM`, `AUDIT ANY` đủ để tạo role/user, cấp `AUDIT_VIEWER` và `CREATE AUDIT POLICY` + `AUDIT POLICY` (đã thấy các privilege này trong `session_privs`, **chưa chạy thử lệnh ghi**). Nếu `CREATE AUDIT POLICY` đòi `AUDIT_ADMIN`, phương án lùi: `apply_security` tự `GRANT AUDIT_ADMIN TO system` hoặc kết nối `SYS AS SYSDBA`.
- Unified audit record được ghi ngay (23ai không còn queued-write) nên AC9 đọc lại được trong cùng test mà không cần `DBMS_AUDIT_MGMT.FLUSH_UNIFIED_AUDIT_TRAIL`.
- Thiếu quyền `SELECT` trên đối tượng → `ORA-00942`; có ít nhất một quyền trên đối tượng nhưng thiếu quyền đang dùng → `ORA-01031`, hoặc `ORA-41900` trên Oracle 23ai (đo thực tế trên 23.26: `ORA-41900: missing <PRIV> privilege on ...`); AC7/AC8 chấp nhận cả hai mã (người dùng xác nhận 2026-10-10).
- Tên họ đầy đủ ở dạng Unicode NFC (dữ liệu Phase 1a); "ký tự đầu" = code point đầu tiên ở cả Python, DuckDB và Oracle (`AL32UTF8`, regex theo ký tự).
- Trigger schema `BEFORE TRUNCATE` không cản `DBMS_MVIEW.REFRESH(..., atomic_refresh => FALSE)` của `acct_edge_daily` (trigger chỉ raise khi tên đối tượng là `AUDIT_LOG`).
- Không test hay code hiện có nào UPDATE/DELETE/TRUNCATE `audit_log` (đã grep `src/`, `tests/`); `load_parquet` không đụng `audit_log`.
- Tên role, tên policy, tên trigger và quy tắc che là **cấu trúc** (hằng trong `aml.dba.security`/`aml.dba.masking` và script SQL), không phải ngưỡng nghiệp vụ nên không đưa vào `config.yaml`; chỉ `admin_user` và 2 secret là cấu hình.
- Test [oracle] tạo role/user/policy thật trong instance dev và để lại sau khi chạy (idempotent, dữ liệu tổng hợp).
- `aml_owner` tiếp tục là user nạp dữ liệu và chạy DDL; `apply_security` ghi `audit_log` bằng kết nối owner với `version='security'`.

## Câu hỏi mở
- [x] Q1. Chạy phần cần quyền DBA bằng cách nào? — đề xuất mặc định: lệnh `aml security-setup` kết nối `SYSTEM` (không `SYS AS SYSDBA`) bằng `ORACLE_SYS_PASSWORD` đọc từ `.env` qua `SECRET_ENV_MAP`; không dùng init script của container. Lý do: init script gvenzl chỉ chạy khi volume được tạo lần đầu (volume hiện đã có), còn lệnh CLI chạy lại được và test gọi trực tiếp được. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q2. Có tạo user đăng nhập cho từng role không, mật khẩu lấy ở đâu? — đề xuất mặc định: 4 user demo `<role>_usr`, chung một mật khẩu từ biến mới `ORACLE_DEMO_PASSWORD` trong `.env`; mỗi lần chạy `ALTER USER` đồng bộ lại mật khẩu. Lý do: không có user thì không kiểm chứng được least privilege; một biến là đủ cho demo dữ liệu tổng hợp (prod: mỗi user một secret trong vault). — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q3. Thiếu `ORACLE_SYS_PASSWORD`/`ORACLE_DEMO_PASSWORD` thì test [oracle] của 2b fail hay skip? — đề xuất mặc định: skip với thông điệp nêu tên biến; `aml security-setup` thì exit 2. Lý do: giữ `pytest` xanh trên máy chỉ có `.env` cũ. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q4. Ma trận quyền như bảng "Ma trận quyền"? — đề xuất mặc định: đúng như bảng; `aml_app` chỉ `INSERT` (không `SELECT`) trên `audit_log` và chưa có DML trên bảng dữ liệu (loader vẫn là owner); `aml_auditor` chỉ đọc `audit_log` + `AUDIT_VIEWER`, không đọc dữ liệu khách hàng; không role nào thấy `ground_truth`/`dq_labels`. Lý do: khớp comment trong `000_audit_log.sql` và tránh lộ nhãn đánh giá. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q5. `aml_graph_sync` đọc `customers` hay `customers_masked`? — đề xuất mặc định: `customers_masked` (+ `accounts`, `transactions`, `acct_edge_daily`), không đọc `customer_person`. Lý do: Neo4j Community không có RBAC nên mọi thứ sync sang đều lộ cho người điều tra; Phase 5 mở rộng nếu cần. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q6. Quy tắc che tên? — đề xuất mặc định: giữ họ (token đầu), các token sau còn chữ cái đầu + `.` (`Nguyễn T. Đ.`). Lý do: analyst vẫn nhận diện sơ bộ được mà không lộ tên đầy đủ; viết được bằng regex ở cả Oracle và DuckDB. Phương án khác: che cả họ (`N. T. Đ.`). — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q7. Quy tắc che số giấy tờ và điện thoại? — đề xuất mặc định: giấy tờ giữ 4 ký tự cuối; điện thoại chuẩn về chữ số rồi giữ 3 số cuối (mất định dạng `085.250.0337`/`+84 ...`); phần còn lại là `*` cùng độ dài. Lý do: đủ để đối chiếu qua điện thoại, không đủ để tái tạo. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q8. Brief chỉ nêu tên/ID/phone — các PII khác của `customers` xử lý sao? — đề xuất mặc định: `email` che (`d***@icloud.com`); `dob` thay bằng `birth_year`; bỏ hẳn `street`, `address`, `device_id`, `ip`; giữ `ward`/`district`/`province`. Lý do: view cho analyst mà còn email/địa chỉ đầy đủ thì masking vô nghĩa. Lưu ý: analyst xử lý cảnh báo screening có thể cần DOB đầy đủ — nếu vậy đổi thành giữ `dob`. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q9. Có che PII trong `transactions` (`counterparty_name`, `memo`, `device_id`, `ip`) không? — đề xuất mặc định: không ở 2b; analyst đọc `transactions` nguyên bản. Lý do: điều tra cần memo và tên đối tác; ghi rõ là giới hạn đã biết. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q10. Policy unified audit bao trùm gì? — đề xuất mặc định: `AML_PII_ACCESS` (mọi DML + SELECT trên `customers`, `customer_person`; SELECT trên `customers_masked`) và `AML_AUDIT_LOG_TAMPER` (UPDATE/DELETE trên `audit_log`), áp cho mọi user kể cả owner, cả thành công lẫn thất bại; không audit `transactions`. Lý do: `transactions` bị đọc liên tục bởi rule/trace sẽ làm phình audit trail trên bản Free. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q11. Trigger append-only mức nào và có chặn TRUNCATE không? — đề xuất mặc định: trigger statement-level `ORA-20100` cho UPDATE/DELETE (chặn cả owner) + trigger schema `BEFORE TRUNCATE` `ORA-20101`; không chặn `DROP`/`DISABLE TRIGGER` (owner vẫn làm được — nêu là rủi ro còn lại, giảm thiểu bằng audit policy). Lý do: TRUNCATE bỏ qua trigger DML nên phải chặn riêng. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q12. Trigger và view đặt trong `apply_schema` hay chỉ trong `security-setup`? — đề xuất mặc định: trong `apply_schema` (`ddl/050_*`), vì không cần quyền admin và `audit_log` nên được bảo vệ ngay từ `aml init-db`; grants/roles/policy mới cần `security-setup`. Hệ quả: 2c không thể purge `audit_log` bằng DELETE (đã loại khỏi purge ở Q14 của 2a). — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q13. DuckDB có gì? — đề xuất mặc định: view `customers_masked` cùng tên/cột/quy tắc với Oracle và hàm Python `aml.dba.masking` làm chuẩn đối chiếu (AC2, AC10); không giả lập role/trigger. Lý do: Phase 9 cần đọc view đã che ở cả hai backend. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q14. `apply_security` ghi `audit_log` thế nào? — đề xuất mặc định: mỗi lần chạy thành công ghi 1 dòng `SECURITY_APPLIED` (kể cả lần chạy lại, vì grants/mật khẩu được áp lại thật), `details` gồm `roles`, `users`, `policies`. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
- [x] Q15. Tên role/policy và tham số che có đưa vào `config.yaml` không? — đề xuất mặc định: không; là hằng trong code + SQL (như tên bảng), được test đối chiếu Python ↔ SQL bảo vệ. Lý do: codebase không có cơ chế template cho file `.sql`; cấu hình hoá sẽ kéo theo dựng SQL động cho DDL bảo mật. — Trả lời: theo đề xuất mặc định (người dùng xác nhận 2026-10-10).
