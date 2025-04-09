import streamlit as st
import requests
import pandas as pd
import time

TIMEOUT = 30
API_BASE_URL = "https://api.beezup.com/v2/user"


def get_headers():
    """Récupère les headers pour les requêtes API avec gestion d'erreurs."""
    try:
        token = st.session_state.bzp_token.strip()
        return {
            "Content-Type": "application/json",
            "Ocp-Apim-Subscription-Key": token
        }
    except Exception as e:
        st.error(f"Erreur lors de la préparation des headers: {str(e)}")
        return None


@st.cache_data(ttl=3600, show_spinner=False)  # Cache pendant 1 heure
def get_column_id_list(catalog_id):
    """Récupère la liste des attributs éditables pour un catalogue."""
    try:
        headers = get_headers()
        if headers is None:
            raise Exception("Headers invalides")

        url = f"{API_BASE_URL}/channelCatalogs/{catalog_id}"
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()

        response_json = response.json()
        column_mappings = response_json.get("columnMappings", [])

        return pd.DataFrame([
            {
                "Column Name": column.get("channelColumnName"),
                "Column Id": column.get("channelColumnId")
            }
            for column in column_mappings
        ])

    except requests.exceptions.RequestException as e:
        st.error(f"Erreur lors de l'extraction des attributs: {str(e)}")
        raise


def get_skus_list(file_path):
    """Lit le fichier Excel contenant les SKUs à éditer."""
    try:
        df = pd.read_excel(file_path)
        return df
    except Exception as e:
        st.error(f"Erreur lors de la lecture du fichier Excel: {str(e)}")
        return None


@st.cache_data(ttl=3600, show_spinner=False)  # Cache pendant 1 heure
def prepare_template(catalog_id, column_id, skus_list, df_values):
    """Prépare le template d'édition avec gestion de pagination."""
    try:
        headers = get_headers()
        if headers is None:
            raise Exception("Headers invalides")

        url = f"{API_BASE_URL}/channelCatalogs/{catalog_id}/products"
        data = []

        payload = {
            "pageNumber": 1,
            "pageSize": 1000,
            "criteria": {
                "logic": "cumulative",
                "exist": True,
                "uncategorized": False,
                "excluded": False,
                "disabled": False
            },
            "productFilters": {
                "catalogSkus": skus_list
            }
        }

        while True:
            response = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
            response.raise_for_status()

            pagination_result = response.json().get("paginationResult", {})
            page_count = pagination_result.get("pageCount", 0)
            product_infos = response.json().get("productInfos", [])

            for product in product_infos:
                sku = product.get("productSku", "").strip()
                value = df_values[df_values["Skus"] == sku]["Values"].iloc[0] if \
                    len(df_values[df_values["Skus"] == sku]) > 0 else ""

                data.append({
                    "Product Id": product.get("productId"),
                    "Product Sku": sku,
                    "Catalog Id": catalog_id,
                    "Column Id": column_id,
                    "Replacement Value": value
                })

            if payload["pageNumber"] >= page_count:
                print("\nTemplate prêt pour l'édition produits")
                return pd.DataFrame(data)

            payload["pageNumber"] += 1
            time.sleep(0.5)

    except requests.exceptions.RequestException as e:
        st.error(f"Erreur lors de la préparation du template: {str(e)}")
        return None


@st.cache_data(ttl=3600, show_spinner=False)  # Cache pendant 1 heure
def override_with_progress(df_template):
    """Édite les produits avec une barre de progression."""
    try:
        progress_bar = st.progress(0)
        total_products = len(df_template)
        data = []

        for index, row in df_template.iterrows():
            product_id = row["Product Id"]
            catalog_id = row["Catalog Id"]
            column_id = row["Column Id"]
            replacement_value = row["Replacement Value"]

            url = f"{API_BASE_URL}/channelCatalogs/{catalog_id}/products/{product_id}/overrides"
            payload = {column_id: replacement_value}

            response = requests.put(url, headers=get_headers(), json=payload)
            status = "OK" if response.status_code == 204 else response.status_code

            data.append({"Override Status": status})

            progress_value = (index + 1) / total_products
            progress_bar.progress(progress_value)

            if index == total_products - 1:
                st.success("Édition terminée avec succès !")

        return pd.DataFrame(data)

    except requests.exceptions.RequestException as e:
        st.error(f"Erreur lors de l'édition des produits: {str(e)}")
        return None


def main():
    # Configuration initiale du session_state
    if "bzp_token" not in st.session_state:
        st.session_state.bzp_token = ""

    # Barre latérale simplifiée
    with st.sidebar:
        st.subheader("PANNEAU DE CONFIGURATION")
        st.text_input("*Token Primaire BeezUP*", key="bzp_token")

        # Chargement des données vendeurs avec cache
        df_sellers_db_path = "./data/Mkp_Channel_Catalog_List.xlsx"

        @st.cache_data(ttl=3600, show_spinner=False)
        def load_sellers_db():
            return pd.read_excel(df_sellers_db_path)

        df_sellers_db = load_sellers_db()

        # Sélections simplifiées
        sales_channel = st.selectbox(
            "*Sélectionnez un Canal de Vente*",
            options=df_sellers_db["Sales Channel"].unique()
        )

        sellers_df = df_sellers_db[df_sellers_db["Sales Channel"] == sales_channel]
        seller_id = st.selectbox(
            "*Sélectionnez un Seller Id*",
            options=sellers_df["Seller Id"].unique()
        )

        if seller_id:
            catalog_data = sellers_df[sellers_df["Seller Id"] == seller_id].iloc[0]
            catalog_id = catalog_data["BeezUP Channel Catalog Id"]
            store_name = catalog_data["BeezUP Store Name"]

    # Page principale
    st.title("EDITION PRODUITS BEEZUP")

    # Validation simplifiée
    if not st.session_state.bzp_token.strip():
        st.error("Veuillez entrer un token valide")
        return

    # Sélection de l'attribut
    df_column_list = get_column_id_list(catalog_id)
    column_name = st.selectbox("*Sélectionnez un attribut à éditer*",
                               sorted(df_column_list["Column Name"]))
    column_id = df_column_list[df_column_list["Column Name"] == column_name]["Column Id"].iloc[0]

    # Chargement et traitement du fichier
    file_path = st.file_uploader("*Sélectionnez le fichier Excel des skus à éditer*",
                                 type="xlsx")
    if file_path:
        df_skus_to_edit = get_skus_list(file_path)
        df_skus_to_edit["Skus"] = df_skus_to_edit["Skus"].str.strip()
        skus_list = df_skus_to_edit["Skus"].to_list()

        # Préparation du template avec gestion d'erreurs
        try:
            with st.spinner("Préparation du template en cours..."):
                df_template = prepare_template(catalog_id, column_id, skus_list, df_skus_to_edit)

            if df_template is not None:
                st.success("Template prêt pour l'édition produits")
                st.write(df_template)

                # Edition des produits
                if st.button("Editer"):
                    override_status = override_with_progress(df_template)
                    df_template["Override Status"] = override_status
                    st.write(df_template)

        except Exception as e:
            st.error(f'Erreur lors du traitement : {str(e)}')


if __name__ == "__main__":
    main()
