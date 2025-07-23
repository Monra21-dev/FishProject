from flask import Flask, request, jsonify, render_template
import pandas as pd
import webbrowser
from collections import OrderedDict
import json

app = Flask(__name__)

# Load and preprocess CSV
df = pd.read_csv("FishProject\\FishTable.csv")
df["Buy Price"] = pd.to_numeric(df["Buy Price"].astype(str).str.replace(",", ""), errors="coerce")
df["Sell Price"] = pd.to_numeric(df["Sell Price"].astype(str).str.replace(",", ""), errors="coerce")
df["Weight"] = pd.to_numeric(df["Weight"], errors="coerce")
df["Profit %"] = ((df["Sell Price"] - df["Buy Price"]) / df["Buy Price"]) * 100

def parse_mods(val):
    try:
        mods = json.loads(val)
        if isinstance(mods, list):
            return [m.strip().title() for m in mods if m.strip()]
        else:
            return []
    except Exception:
        # fallback for legacy rows
        return [m.strip().title() for m in str(val).split(",") if m.strip()]

df["Modifiers"] = df["Modifiers"].fillna("[]").apply(parse_mods)

# Utility to filter and sort
def format_value(value, col, row=None):
    if "Price" in col:
        try:
            value = int(value)
            if value == 0:
                if col == "Buy Price":
                    return "Limited-Time Event"
                if col == "Sell Price":
                    return "Unknown"
            return f"${value:,}"
        except:
            return value
    elif col == "Profit %":
        try:
            if pd.isna(value):
                return "N/A"
            sell = row.get("Sell Price", 0) if row is not None else 0
            buy = row.get("Buy Price", 0) if row is not None else 0
            if sell == 0 or buy == 0:
                return "N/A"
            return f"{value:.2f}%"
        except:
            return "N/A"
    elif col == "Weight":
        try:
            return f"{value:,.2f} kg"
        except:
            return value
    elif col == "Logger":
        # Show "Pre-Beta Data" if Logger is missing or empty
        if pd.isna(value) or str(value).strip() == "":
            return "Pre-Beta Data"
        return value
    elif isinstance(value, list):
        return ", ".join(value)
    return value



def get_top_fish(kind="best", metric="Sell Price", top_n=1, filters={}):
    filtered = df.copy()

    # Apply filters
    if filters.get("repro"):
        filtered = filtered[filtered["Reproduction"].str.upper() == filters["repro"].upper()]

    if filters.get("rarity"):
        rarity_raw = filters["rarity"]
        if isinstance(rarity_raw, list):
            rarity_list = [r.strip().lower() for r in rarity_raw if r.strip()]
        else:
            rarity_list = [r.strip().lower() for r in str(rarity_raw).split(",") if r.strip()]
        filtered = filtered[filtered["Rarity"].str.lower().isin(rarity_list)]
         
    if filters.get("name"):
        name_list = [n.strip().lower() for n in filters["name"].split(",") if n.strip()]
        filtered = filtered[filtered["Name"].str.lower().apply(lambda name: any(n in name for n in name_list))]


    if filters.get("mods"):
        # Accept both array and string for backward compatibility
        mods_raw = filters["mods"]
        if isinstance(mods_raw, list):
            mod_list = [m.strip().title() for m in mods_raw if m.strip()]
        else:
            mod_list = [m.strip().title() for m in str(mods_raw).split(",") if m.strip()]
        mods_mode = filters.get("mods_mode", "contains")
        def normalize(lst):
            return sorted([str(m).strip().title() for m in lst if str(m).strip()])
        if mods_mode == "strict":
            filtered = filtered[filtered["Modifiers"].apply(
                lambda mods: normalize(mods) == normalize(mod_list)
            )]
        else:
            filtered = filtered[filtered["Modifiers"].apply(
                lambda mods: all(m in normalize(mods) for m in normalize(mod_list))
            )]

    if filters.get("logger"):
        logger_list = [l.strip() for l in str(filters["logger"]).split(",") if l.strip()]
        if logger_list:
            filtered = filtered[filtered["Logger"].fillna("N/A").apply(
                lambda logger: any(l == logger for l in logger_list)
            )]

    if metric == "Profit %" and kind == "best":
    # Remove rows where Buy or Sell Price is 0 to avoid N/A result
        filtered = filtered[(filtered["Buy Price"] > 0) & (filtered["Sell Price"] > 0)]



    # Sort by metric
    ascending = kind == "worst"
    sorted_fish = filtered.sort_values(metric, ascending=ascending).head(top_n)

    # Drop the Ratio column if it exists
    if "Ratio" in sorted_fish.columns:
        sorted_fish = sorted_fish.drop(columns=["Ratio"])

    fixed_order = []

    # Always start with Name
    if "Name" in sorted_fish.columns:
        fixed_order.append("Name")

    # Add selected metric next
    if metric in sorted_fish.columns and metric != "Name":
        fixed_order.append(metric)

    # Always follow with Buy and Sell Price if not already added
    for col in ["Buy Price", "Sell Price"]:
        if col in sorted_fish.columns and col not in fixed_order:
            fixed_order.append(col)

    # Add Logger after Sell Price if present
    if "Logger" in sorted_fish.columns and "Logger" not in fixed_order:
        fixed_order.append("Logger")

    # Add all remaining columns
    for col in sorted_fish.columns:
        if col not in fixed_order:
            fixed_order.append(col)

    # Build formatted records
    records = []
    for _, row in sorted_fish.iterrows():
        ordered = OrderedDict()
        for col in fixed_order:
            ordered[col] = format_value(row[col], col, row)
        records.append(ordered)

    return records


# Routes
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/query", methods=["POST"])
def query():
    try:
        data = request.json or {}
        kind = data.get("kind", "best")
        metric = data.get("metric", "Sell Price")
        top_n = int(data.get("top_n", 1))
        filters = data.get("filters", {})

        result = get_top_fish(kind, metric, top_n, filters)
        return jsonify(result)
    except Exception as e:
        print("QUERY ERROR:", e)  # Add this line for debugging
        return jsonify({"error": str(e)}), 500
    
@app.route("/log_counts")
def log_counts():
    # Ensure no NaN in Rarity or Name
    temp_df = df.copy()
    temp_df["Rarity"] = temp_df["Rarity"].fillna("Unknown").astype(str)
    temp_df["Name"] = temp_df["Name"].fillna("Unknown").astype(str)

    grouped = {}
    for _, row in temp_df.iterrows():
        rarity = row["Rarity"]
        name = row["Name"]
        grouped.setdefault(rarity, {})
        grouped[rarity][name] = grouped[rarity].get(name, 0) + 1

    # Optional: Sort rarities alphabetically and names inside each group
    sorted_grouped = {
        rarity: dict(sorted(grouped[rarity].items()))
        for rarity in sorted(grouped)
    }

    return jsonify(sorted_grouped)

@app.route("/logger_stats")
def logger_stats():
    temp_df = df.copy()
    # Replace N/A with "Pre-Beta Data"
    temp_df["Logger"] = temp_df["Logger"].fillna("Pre-Beta Data").astype(str)
    temp_df.loc[temp_df["Logger"].str.strip() == "", "Logger"] = "Pre-Beta Data"
    logger_counts = temp_df["Logger"].value_counts().sort_values(ascending=False).to_dict()
    return jsonify(logger_counts)

if __name__ == "__main__":
    chrome_path = "C:/Program Files/Google/Chrome/Application/chrome.exe %s"
    import os

    # Only open browser if not reloading (WERKZEUG_RUN_MAIN is not set)
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        webbrowser.get(chrome_path).open("http://127.0.0.1:5000/")

    app.run(debug=True, use_reloader=True)

