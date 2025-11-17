# Streamlit SpendWise: single-file app with registration, login, CRUD, KPIs, and pie chart
# Run: streamlit run app.py

import streamlit as st
import sqlite3
import hashlib
import pandas as pd
import plotly.express as px
from datetime import date

# ---------- Config ----------
st.set_page_config(page_title="SpendWise", page_icon="💸", layout="wide")

DB_PATH = "spendwise.db"

# categories
CATEGORIES = [
    "Food & Groceries",
    "Transport",
    "Housing",
    "Utilities",
    "Entertainment",
    "Shopping",
    "Health",
    "Education",
    "Travel",
    "Subscriptions",
    "Income",
    "Other",
]

# ---------- DB helpers ----------
@st.cache_resource
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            UNIQUE(user_id, category),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            date TEXT NOT NULL,
            note TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    """)
    # <<< НОВОЕ: таблица пользовательских категорий >>>
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            UNIQUE(user_id, name),
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    """)

    conn.commit()
    return conn



def hash_password(p: str) -> str:
    # Minimal demo hashing (not for production)
    return hashlib.sha256(("spendwise_salt__" + p).encode("utf-8")).hexdigest()

def find_user_by_email(conn, email: str):
    cur = conn.execute("SELECT id, email, password_hash FROM users WHERE email = ?", (email,))
    return cur.fetchone()  # (id, email, password_hash) or None

def create_user(conn, email: str, password: str):
    try:
        conn.execute(
            "INSERT INTO users (email, password_hash) VALUES (?, ?)",
            (email, hash_password(password)),
        )
        conn.commit()
        return True, None
    except sqlite3.IntegrityError as e:
        return False, "Email already registered"

def insert_tx(conn, user_id: int, amount: float, category: str, iso_date: str, note: str | None):
    conn.execute(
        "INSERT INTO transactions (user_id, amount, category, date, note) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, category, iso_date, note or None),
    )
    conn.commit()

def delete_tx(conn, user_id: int, tx_id: int):
    conn.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (tx_id, user_id))
    conn.commit()

def update_tx(conn, user_id: int, tx_id: int, amount: float, category: str, iso_date: str, note: str | None):
    conn.execute(
        "UPDATE transactions SET amount=?, category=?, date=?, note=? WHERE id=? AND user_id=?",
        (amount, category, iso_date, note or None, tx_id, user_id),
    )
    conn.commit()

# Insert or update a budget for a specific category
def upsert_budget(conn, user_id: int, category: str, amount: float):
    conn.execute(
        """
        INSERT INTO budgets (user_id, category, amount)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, category) DO UPDATE SET amount=excluded.amount
        """,
        (user_id, category, amount),
    )
    conn.commit()

def load_transactions_df(conn, user_id: int) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT id, amount, category, date, note FROM transactions WHERE user_id = ? ORDER BY date DESC, id DESC",
        conn,
        params=(user_id,),
    )
    # Ensure correct dtypes
    if not df.empty:
        df["amount"] = df["amount"].astype(float)
    return df

def kpi_from_df(df: pd.DataFrame) -> tuple[float, float, int]:
    total = float(df["amount"].sum()) if not df.empty else 0.0
    unique_days = df["date"].nunique() if not df.empty else 1
    avg_per_day = total / max(unique_days, 1)
    tx_count = len(df)
    return total, avg_per_day, tx_count



# ---------- Session ----------
if "user" not in st.session_state:
    st.session_state.user = None  # {"id": int, "email": str}

# ---------- Categories (base + custom) ----------

def get_user_categories(conn, user_id: int) -> list[str]:
    """Пользовательские категории из таблицы user_categories."""
    cur = conn.execute(
        "SELECT name FROM user_categories WHERE user_id = ? ORDER BY name",
        (user_id,),
    )
    rows = cur.fetchall()
    return [r[0] for r in rows]

def get_all_categories(conn, user_id: int) -> list[str]:
    """Базовые + пользовательские категории (без дублей)."""
    base = CATEGORIES.copy()
    user_cats = get_user_categories(conn, user_id)
    for c in user_cats:
        if c not in base:
            base.append(c)
    return base


# -----------> UI: Header <---------------


left, right = st.columns([0.8, 0.2])
with left:
    st.markdown("## SpendWise")
with right:
    # Custom CSS for compact horizontal button
    st.markdown("""
        <style>
        div[data-testid="stVerticalBlock"] button[kind="secondary"],
        div[data-testid="stVerticalBlock"] button {
            writing-mode: horizontal-tb !important;
            text-orientation: mixed !important;
            transform: none !important;
            padding: 0.25rem 0.8rem !important;
            font-size: 0.85rem !important;
            width: auto !important;
            height: auto !important;
        }
        </style>
    """, unsafe_allow_html=True)

    if st.session_state.user:
        st.markdown(
            f"<div style='text-align:right;font-size:0.9rem;'>"
            f"Signed in as <b>{st.session_state.user['email']}</b></div>",
            unsafe_allow_html=True
        )
        if st.button("Log out", key="logout_btn_header"):
            st.session_state.user = None
            st.success("Signed out")
            st.rerun()
    else:
        if st.button("Log in", key="login_btn_header"):
            st.session_state.show_auth = True

# ---------- Auth Dialog (simulated with expander in sidebar for compatibility) ----------
conn = get_conn()

# Use sidebar as a persistent, familiar place for auth controls
with st.sidebar:
    # --- Style tweaks ---
    st.markdown("""
        <style>
        /* Sidebar styling */
        [data-testid="stSidebar"] {
            font-size: 0.9rem;       /* smaller text */
            line-height: 1.4;        /* compact line spacing */
        }
        [data-testid="stSidebar"] h3, 
        [data-testid="stSidebar"] h2, 
        [data-testid="stSidebar"] label {
            font-size: 0.95rem !important;
        }
        [data-testid="stSidebar"] input, 
        [data-testid="stSidebar"] button, 
        [data-testid="stSidebar"] select {
            font-size: 0.9rem !important;
        }
        </style>
    """, unsafe_allow_html=True)

    # --- Auth panel ---
    st.markdown("### Account")
    if st.session_state.user:
        st.success(f"Signed in as **{st.session_state.user['email']}**")
        if st.button("Log out (sidebar)"):
            st.session_state.user = None
            st.success("Signed out")
            st.rerun()
    else:
        tabs = st.tabs(["Sign in", "Sign up"])
        with tabs[0]:
            with st.form("signin_form"):
                email_in = st.text_input("Email", key="signin_email", placeholder="you@example.com")
                pwd_in = st.text_input("Password", type="password", key="signin_pwd")
                submitted = st.form_submit_button("Log in")
                if submitted:
                    row = find_user_by_email(conn, email_in.strip())
                    if not row or hash_password(pwd_in) != row[2]:
                        st.error("Incorrect email or password")
                    else:
                        st.session_state.user = {"id": row[0], "email": row[1]}
                        st.success("Signed in")
                        st.rerun()
        with tabs[1]:
            with st.form("signup_form"):
                email_up = st.text_input("Email", key="signup_email", placeholder="you@example.com")
                pwd_up = st.text_input("Password (min 6 chars)", type="password", key="signup_pwd")
                submitted_up = st.form_submit_button("Create account")
                if submitted_up:
                    if len(pwd_up) < 6:
                        st.error("Password too short")
                    else:
                        ok, err = create_user(conn, email_up.strip(), pwd_up)
                        if ok:
                            st.success("Account created, you can sign in now")
                        else:
                            st.error(err or "Registration failed")

# ---------- Guard (app content requires auth) ----------
if not st.session_state.user:
    st.info("Please sign in to manage your transactions.")
    st.stop()

user_id = st.session_state.user["id"]

# ---------- Add Category ----------
# ---------- Add Category ----------
st.markdown("### Add category")

left_col, right_col = st.columns([2, 2])

# Инициализация состояния для поля и сообщений
if "new_category_name" not in st.session_state:
    st.session_state.new_category_name = ""

if "add_cat_feedback" not in st.session_state:
    st.session_state.add_cat_feedback = None  # (level, text)


# --- колбэк для кнопки Add ---
def handle_add_category():
    name = (st.session_state.new_category_name or "").strip()

    if not name:
        st.session_state.add_cat_feedback = ("warning", "Please enter a category name.")
        return

    all_cats_lower = [c.lower() for c in get_all_categories(conn, user_id)]
    if name.lower() in all_cats_lower:
        st.session_state.add_cat_feedback = ("info", "This category already exists.")
        return

    # пишем в БД
    conn.execute(
        "INSERT INTO user_categories (user_id, name) VALUES (?, ?)",
        (user_id, name),
    )
    conn.commit()

    # сообщение + очистка поля
    st.session_state.add_cat_feedback = ("success", f"Category '{name}' added.")
    st.session_state.new_category_name = ""


# ---------- ЛЕВАЯ ЧАСТЬ: добавить категорию ----------
with left_col:
    st.write(
        "Create your own spending or income category. "
        "New categories will appear in all dropdown lists (transactions, filters, budgets)."
    )

    st.text_input(
        "Category name",
        key="new_category_name",
        placeholder="e.g. Pets, Gifts, Freelance",
    )

    st.button(
        "Add",
        key="add_category_button",
        on_click=handle_add_category,
    )

    # показываем сообщение из состояния
    fb = st.session_state.add_cat_feedback
    if fb:
        level, msg = fb
        if level == "success":
            st.success(msg)
        elif level == "warning":
            st.warning(msg)
        elif level == "info":
            st.info(msg)

# ---------- ПРАВАЯ ЧАСТЬ: удалить существующую категорию ----------
with right_col:
    st.write("Delete an existing category")

    existing_cats = get_all_categories(conn, user_id)

    if not existing_cats:
        st.caption("There are no categories to display.")
    else:
        cat_to_delete = st.selectbox(
            "Select category",
            options=existing_cats,
            key="delete_category_select",
        )

        delete_cat_clicked = st.button(
            "Delete",
            key="delete_category_button",
            type="secondary",
        )

        if delete_cat_clicked:
            if cat_to_delete in CATEGORIES:
                st.warning("Base categories cannot be deleted.")
            else:
                conn.execute(
                    "DELETE FROM user_categories WHERE user_id = ? AND name = ?",
                    (user_id, cat_to_delete),
                )
                conn.commit()
                st.success(f"Category '{cat_to_delete}' deleted.")


# ---------- Budget ----------

st.markdown("### Set budget")
st.write("Set a monthly budget for each category below.")


st.markdown("""
<style>
/* Make SET light green */
button[kind="primary"][data-testid="baseButton-secondary"] {
    background-color: #d9fdd3 !important;   /* light green */
    color: #0b3d0b !important;
}

/* Make RESET light red */
button[kind="secondary"][data-testid="baseButton-secondary"] {
    background-color: #ffe0e0 !important;   /* light red */
    color: #7a1414 !important;
}
</style>
""", unsafe_allow_html=True)

with st.form("set_budget_form_budget", clear_on_submit=False):
    # Wrap buttons in a container for CSS targeting
    st.markdown('<div class="budget-form">', unsafe_allow_html=True)

    bc1, bc2, bc3, bc4 = st.columns([1, 1, 1, 1])

    # все категории (базовые + добавленные через "Add category")
    all_categories_for_budget = get_all_categories(conn, user_id)

    with bc1:
        budget_category = st.selectbox(
            "Category",
            options=all_categories_for_budget,
            key="budget_category_form",
            help="Start typing to search categories",
        )

    with bc2:
        budget_amount = st.number_input(
            "Budget amount",
            min_value=0.0,
            step=0.01,
            format="%.2f",
            key="budget_amount_form",
        )

    # Set и Reset в ОДНОМ столбце, один под другим
    with bc3:
        set_budget_clicked = st.form_submit_button("Set", type="secondary")
        reset_clicked = st.form_submit_button("Reset", type="primary")

    # Reset all отдельно справа
    with bc4:
        reset_all_clicked = st.form_submit_button("Reset all")

    st.markdown('</div>', unsafe_allow_html=True)

# --- Actions ---
if set_budget_clicked:
    if budget_amount and budget_amount > 0:
        upsert_budget(conn, user_id, budget_category, float(budget_amount))
        st.success(f"Budget saved for {budget_category}")

if reset_clicked:
    conn.execute(
        "DELETE FROM budgets WHERE user_id = ? AND category = ?",
        (user_id, budget_category),
    )
    conn.commit()
    st.warning(f"Budget reset for {budget_category}")
    st.rerun()

if reset_all_clicked:
    conn.execute("DELETE FROM budgets WHERE user_id = ?", (user_id,))
    conn.commit()
    st.warning("All budgets were reset")
    st.rerun()





# ---------- Budget Status Grid ----------
# ---------- Budget Status Grid (first 8 + expandable rest) ----------

st.markdown("### Budget overview")
st.markdown("Here you can see your category budgets and how much you’ve spent.")

# Загружаем бюджеты
cur_all = conn.execute(
    "SELECT category, amount FROM budgets WHERE user_id = ?",
    (user_id,),
).fetchall()

budget_map = {row[0]: float(row[1]) for row in cur_all}

# Получаем все категории (включая кастомные, если они есть)
all_categories = get_all_categories(conn, user_id)


# Разделяем первые 8 и остальные
first_block = all_categories[:8]
rest_block = all_categories[8:]

# --- Функция рисования карточек ---
def draw_budget_cards(category_list):
    cols = st.columns(4)
    for i, cat in enumerate(category_list):
        # spent
        cur_s = conn.execute(
            "SELECT SUM(amount) FROM transactions WHERE user_id = ? AND category = ?",
            (user_id, cat),
        )
        row_s = cur_s.fetchone()
        spent_val = float(row_s[0]) if row_s and row_s[0] is not None else 0.0

        # budget
        budget_val = budget_map.get(cat, 0.0)

        # color
        percent = (spent_val / budget_val * 100.0) if budget_val > 0 else 0.0
        if budget_val == 0:
            bg = "#f0f0f0"
            border = "#cccccc"
        elif percent < 80:
            bg = "#e6f4ea"
            border = "#34a853"
        elif percent < 100:
            bg = "#fff4e5"
            border = "#f9ab00"
        else:
            bg = "#fce8e6"
            border = "#d93025"

        with cols[i % 4]:
            st.markdown(
                f"""
                <div style="
                    border:1px solid {border};
                    background:{bg};
                    border-radius:6px;
                    padding:0.5rem 0.6rem;
                    margin-bottom:0.6rem;
                    font-size:0.75rem;
                ">
                    <b>{cat}</b><br>
                    {"No budget set" if budget_val == 0 else f"HUF{spent_val:,.2f} / HUF{budget_val:,.2f} ({percent:.1f}%)"}
                </div>
                """,
                unsafe_allow_html=True,
            )

# --- Рисуем первые 8 категорий ---
draw_budget_cards(first_block)

# --- Остальные показываем только внутри expander ---
if rest_block:
    with st.expander("Show more categories", expanded=False):
        draw_budget_cards(rest_block)




# ----------
# ---------- Data + Filters ----------
st.markdown("### Add Transaction")
with st.form("add_tx_form", clear_on_submit=True):
    c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
    with c1:
        amount = st.number_input("Amount", min_value=0.0, step=0.01, format="%.2f")
    with c2:
        category = st.selectbox(
            "Category",
            options=get_all_categories(conn, user_id),
            key="add_category",
            help="Start typing to search categories",
        )

        #category = st.text_input("Category", placeholder="Food / Transport / ...")
    with c3:
        d = st.date_input("Date", value=date.today(), format="YYYY-MM-DD")
    with c4:
        note = st.text_input("Note", placeholder="Optional")
    add_clicked = st.form_submit_button("Add")
    if add_clicked:
        if amount and category and d:
            insert_tx(conn, user_id, float(amount), category.strip(), d.isoformat(), note.strip() if note else None)
            st.success("Saved")
            st.rerun()
        else:
            st.error("Please fill amount, category, and date")

st.markdown("### Overview")
df = load_transactions_df(conn, user_id)

k1, k2, k3 = st.columns(3)
total, avg_per_day, tx_count = kpi_from_df(df)
k1.metric("Total Spending", f"HUF{total:,.2f}")
k2.metric("Avg per Day", f"HUF{avg_per_day:,.2f}")
k3.metric("Transactions", f"{tx_count}")

# Filters
st.markdown("### Filters")

def apply_filters(
    _df: pd.DataFrame,
    cat: str | None,
    from_dt: date | None,
    to_dt: date | None,
) -> pd.DataFrame:
    out = _df.copy()

    # фильтр по категории (точный выбор из списка)
    if cat and cat != "All":
        out = out[out["category"] == cat]

    # фильтры по датам (даты из календаря конвертим в ISO-строку)
    if from_dt:
        out = out[out["date"] >= from_dt.isoformat()]
    if to_dt:
        out = out[out["date"] <= to_dt.isoformat()]

    return out

# Inputs live inside the expander but we compute df_filtered afterwards (no else!)
with st.expander("Filters", expanded=False):
    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        # выбор категории из списка (включая "All" и кастомные)
        cat_filter = st.selectbox(
            "Category",
            options=["All"] + get_all_categories(conn, user_id),
            index=0,
            key="cat_filter",
            help="Choose category to filter or All",
        )

    with fc2:
        # календарь для выбора даты "от"
        from_date = st.date_input(
            "From",
            key="from_date",
        )
    with fc3:
        # календарь для выбора даты "до"
        to_date = st.date_input(
            "To",
            key="to_date",
        )

# Compute filtered dataframe
df_filtered = apply_filters(
    df,
    cat_filter,
    from_date,
    to_date,
)


# Pie chart by category + 7-day moving average & forecast
st.markdown("### Spending overview")

if df_filtered.empty:
    st.info("No data to plot.")
else:
    left_col, right_col = st.columns(2)

    # ----- LEFT: Spending by Category (pie chart) -----
    with left_col:
        st.subheader("Spending by Category")
        pie_df = df_filtered.groupby("category", as_index=False)["amount"].sum()
        fig_pie = px.pie(pie_df, names="category", values="amount", hole=0.35)
        fig_pie.update_layout(legend_title_text="Category")
        st.plotly_chart(fig_pie, use_container_width=True)

    # ----- RIGHT: 7-day moving average & forecast -----
    with right_col:
        st.subheader("7-day average & forecast")

        ts_df = df_filtered.copy()
        ts_df["date"] = pd.to_datetime(ts_df["date"])

        # Daily spending
        daily = (
            ts_df.groupby("date", as_index=False)["amount"]
            .sum()
            .sort_values("date")
        )
        daily.rename(columns={"amount": "Daily spending"}, inplace=True)

        # 7-day moving average
        daily["7-day MA"] = daily["Daily spending"].rolling(window=7, min_periods=1).mean()

        # Last date and last day of the month
        last_date = daily["date"].max()
        last_day_of_month = last_date.to_period("M").to_timestamp("M")

        # Build forecast dataframe (flat forecast using last 7-day MA)
        if last_day_of_month > last_date:
            future_dates = pd.date_range(
                start=last_date + pd.Timedelta(days=1),
                end=last_day_of_month,
                freq="D",
            )
            forecast_value = float(daily["7-day MA"].iloc[-1])
            forecast_df = pd.DataFrame(
                {
                    "date": future_dates,
                    "Series": "Forecast (daily, 7-day avg)",
                    "Amount": forecast_value,
                }
            )
        else:
            forecast_df = pd.DataFrame(columns=["date", "Series", "Amount"])

        # Actual series (daily + 7-day MA) in long format
        actual_long = pd.melt(
            daily,
            id_vars="date",
            value_vars=["Daily spending", "7-day MA"],
            var_name="Series",
            value_name="Amount",
        )

        # Combine actual + forecast
        plot_df = pd.concat([actual_long, forecast_df], ignore_index=True)

        if not plot_df.empty:
            fig_forecast = px.line(
                plot_df,
                x="date",
                y="Amount",
                color="Series",
            )
            fig_forecast.update_layout(
                xaxis_title="Date",
                yaxis_title="Amount",
                legend_title="Series",
            )
            st.plotly_chart(fig_forecast, use_container_width=True)
        else:
            st.info("Not enough data to build forecast yet.")


# Transactions table with inline edit/delete + report download

# Заголовок + кнопка отчёта в одной строке
header_col, btn_col = st.columns([0.7, 0.3])
with header_col:
    st.markdown("### Transactions")
with btn_col:
    if not df_filtered.empty:
        # CSV с разделителем ';' и BOM, чтобы Excel нормально открыл по столбцам
        csv_data = df_filtered.to_csv(
            index=False,
            sep=";",  # <-- главное: разделитель ; вместо ,
        ).encode("utf-8-sig")  # <-- BOM, чтобы Excel корректно понял UTF-8

        st.download_button(
            label="Export report(CSV)",
            data=csv_data,
            file_name="transactions_report.csv",
            mime="text/csv",
        )

if df_filtered.empty:
    st.info("No transactions yet.")
else:
    # Show editable table row-by-row
    for _, row in df_filtered.iterrows():
        with st.expander(f"{row['date']} — {row['category']} — HUF{row['amount']:.2f}", expanded=False):
            ec1, ec2, ec3, ec4, ec5 = st.columns([1, 1, 1, 2, 1])
            with ec1:
                new_amount = st.number_input(
                    "Amount",
                    min_value=0.0,
                    step=0.01,
                    format="%.2f",
                    key=f"edit_amount_{int(row['id'])}",
                    value=float(row["amount"]),
                )

            with ec2:
                edit_categories = get_all_categories(conn, user_id)
                if row["category"] not in edit_categories:
                    edit_categories.append(row["category"])

                new_category = st.selectbox(
                    "Category",
                    options=edit_categories,
                    index=edit_categories.index(row["category"]),
                    key=f"edit_category_{int(row['id'])}",
                    help="Start typing to search categories",
                )

            with ec3:
                # Use text input for ISO flexibility
                new_date = st.text_input(
                    "Date (YYYY-MM-DD)",
                    key=f"edit_date_{int(row['id'])}",
                    value=row["date"],
                )
            with ec4:
                new_note = st.text_input(
                    "Note",
                    key=f"edit_note_{int(row['id'])}",
                    value=row["note"] if pd.notna(row["note"]) else "",
                )
            with ec5:
                if st.button("Save", key=f"save_{int(row['id'])}"):
                    if new_amount and new_category and new_date:
                        update_tx(
                            conn,
                            user_id,
                            int(row["id"]),
                            float(new_amount),
                            new_category.strip(),
                            new_date.strip(),
                            new_note.strip() if new_note else None,
                        )
                        st.success("Updated")
                        st.rerun()
                    else:
                        st.error("Fill amount, category, and date")
                if st.button("Delete", key=f"delete_{int(row['id'])}"):
                    delete_tx(conn, user_id, int(row["id"]))
                    st.warning("Deleted")
                    st.rerun()


# Footer
st.caption("SpendWise project • Dubrovskaia Elena (OAC994) • Liu Zerui (RW0KYH)")

# only for report (to show databases)
st.markdown("## Database Inspection (Debug)")

with st.expander("Show database tables and contents", expanded=False):
    # Show list of all tables
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
    ).fetchall()
    table_names = [t[0] for t in tables]

    st.write("**Tables found:**", table_names)

    # Render each table as a dataframe
    for table in table_names:
        st.markdown(f"### Table: `{table}`")
        try:
            df_table = pd.read_sql_query(f"SELECT * FROM {table};", conn)
            st.dataframe(df_table)
        except Exception as e:
            st.error(f"Unable to read table {table}: {e}")

    # Show schema of all tables
    st.markdown("### Schema")
    schema = conn.execute("SELECT sql FROM sqlite_master;").fetchall()
    for entry in schema:
        st.code(entry[0], language="sql")
