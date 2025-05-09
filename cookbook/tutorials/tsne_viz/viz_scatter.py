import streamlit as st
import json
import pandas as pd
import numpy as np
from sklearn.manifold import TSNE
import plotly.express as px

# --- Configuration ---
EMBEDDINGS_FILE = "embeddings.json"
DEFAULT_PERPLEXITY = 30
DEFAULT_ITERATIONS = 300
DEFAULT_LEARNING_RATE = 200

# --- Helper Functions ---

@st.cache_data # Cache data loading
def load_embeddings(filepath: str):
    """Loads embeddings from a JSON file."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Convert to DataFrame for easier handling
        df = pd.DataFrame(data)
        # Ensure embedding is a tuple of floats for hashability
        df['embedding'] = df['embedding'].apply(lambda x: tuple(map(float, x)) if isinstance(x, list) else None)
        df.dropna(subset=['embedding'], inplace=True) # Remove rows with missing embeddings
        if df.empty:
            st.error(f"No valid embeddings found in {filepath}.")
            return None
        if 'id' not in df.columns or 'file_id' not in df.columns or 'content' not in df.columns:
             st.warning("Embeddings file might be missing expected columns: 'id', 'file_id', 'content'. Hover data might be limited.")
        return df
    except FileNotFoundError:
        st.error(f"Error: Embeddings file not found at {filepath}. Please run the indexer first.")
        return None
    except json.JSONDecodeError:
        st.error(f"Error: Could not decode JSON from {filepath}. The file might be corrupted or empty.")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred while loading embeddings: {e}")
        return None

@st.cache_data # Cache t-SNE computation based on data and parameters
def run_tsne(embeddings_df: pd.DataFrame, perplexity: int, n_iter: int, learning_rate: float, random_state: int = 42):
    """Runs t-SNE on the embeddings."""
    if embeddings_df is None or embeddings_df.empty:
        return None

    # Convert tuples back to numpy array for t-SNE
    embeddings_matrix = np.array(embeddings_df['embedding'].tolist())

    if embeddings_matrix.shape[0] <= perplexity:
        st.warning(f"Perplexity ({perplexity}) is too high for the number of samples ({embeddings_matrix.shape[0]}). Setting perplexity to {max(1, embeddings_matrix.shape[0] - 1)}.")
        perplexity = max(1, embeddings_matrix.shape[0] - 1)

    try:
        tsne = TSNE(
            n_components=2,
            perplexity=perplexity,
            max_iter=n_iter,
            learning_rate=learning_rate,
            random_state=random_state,
            init='pca', # Use PCA initialization for stability
            n_jobs=-1 # Use all available CPU cores
        )
        projections = tsne.fit_transform(embeddings_matrix)
        return projections
    except ValueError as ve:
        st.error(f"t-SNE failed. This might be due to invalid parameters (e.g., perplexity too high for the dataset size). Error: {ve}")
        return None
    except Exception as e:
        st.error(f"An unexpected error occurred during t-SNE computation: {e}")
        return None

# --- Streamlit App ---

st.set_page_config(layout="wide")
st.title("🌌 Project embeddings into 2D with t-SNE")

st.markdown(f"""
This app visualizes high-dimensional text embeddings in 2D using t-SNE.
It reads data from `{EMBEDDINGS_FILE}` generated by `indexer.py`.
""")

# --- Load Data ---
with st.spinner(f"Loading embeddings from {EMBEDDINGS_FILE}..."):
    embeddings_df = load_embeddings(EMBEDDINGS_FILE)

if embeddings_df is not None and not embeddings_df.empty:
    st.success(f"Loaded {len(embeddings_df)} embeddings successfully.")

    # --- Sidebar for t-SNE Parameters ---
    st.sidebar.header("t-SNE Parameters")
    perplexity = st.sidebar.slider(
        "Perplexity",
        min_value=5,
        max_value=min(50, embeddings_df.shape[0] - 1 if embeddings_df.shape[0] > 1 else 50), # Adjust max based on data size
        value=min(DEFAULT_PERPLEXITY, embeddings_df.shape[0] - 1 if embeddings_df.shape[0] > 1 else DEFAULT_PERPLEXITY),
        step=1,
        help="Related to the number of nearest neighbors considered for each point. Lower values focus on local structure, higher values on global structure. Must be less than the number of samples."
    )
    n_iter = st.sidebar.slider(
        "Number of Iterations",
        min_value=250,
        max_value=2000,
        value=DEFAULT_ITERATIONS,
        step=50,
        help="Number of optimization iterations."
    )
    learning_rate = st.sidebar.slider(
        "Learning Rate",
        min_value=10,
        max_value=1000,
        value=DEFAULT_LEARNING_RATE,
        step=10,
        help="Controls how much the positions of points are adjusted in each iteration. Usually between 10 and 1000."
    )
    random_state = 42 # Keep random state fixed for reproducibility across runs with same params

    # --- Run t-SNE ---
    with st.spinner("Running t-SNE... (This may take a moment)"):
        projections = run_tsne(embeddings_df, perplexity, n_iter, learning_rate, random_state)

    # --- Create and Display Plot ---
    if projections is not None:
        # st.header("2D Projection of Embeddings")

        # Prepare data for Plotly
        plot_df = pd.DataFrame(projections, columns=['x', 'y'])
        # Safely access columns, providing defaults if missing
        plot_df['file_id'] = embeddings_df['file_id'].values if 'file_id' in embeddings_df else 'N/A'
        # Create a separate column for truncated display content, replacing newlines with <br>
        if 'content' in embeddings_df:
            plot_df['display_content'] = embeddings_df['content'].astype(str).str.replace('\n', '<br>')
        else:
            plot_df['display_content'] = 'N/A'
        plot_df['chunk_id'] = embeddings_df['id'].values if 'id' in embeddings_df else 'N/A'


        # Create interactive scatter plot
        fig = px.scatter(
            plot_df,
            x='x',
            y='y',
            color='file_id', # Color points by the source file
            hover_name='chunk_id', # Show chunk_id on hover title
            # Pass list of column names to make available for hovertemplate
            hover_data=['file_id', 'display_content'],
            title="t-SNE projection of text embeddings",
            labels={'color': 'Source File', 'x': 't-SNE Dimension 1', 'y': 't-SNE Dimension 2'}
        )

        fig.update_layout(
            height=750,
            showlegend=False, # Hide the color legend
            hoverlabel=dict(
                bgcolor="rgba(50, 50, 50, 0.8)",
                font_color="white",
                font_size=12,
                font_family="sans-serif", # Use a standard sans-serif for better readability
                align="left"
            ),
            hovermode='closest' # Ensure hover appears for the nearest point
        )

        # Custom hover template for better structure and wrapping attempt
        fig.update_traces(hovertemplate=(
            "<b>Chunk ID:</b> %{hovertext}<br>" +
            "<b>File:</b> %{customdata[0]}<br>" +
            "<b>Content:</b><br>" +
            "<span style='display: block; max-width: 400px; white-space: normal; word-wrap: break-word;'>%{customdata[1]}</span>" +
            "<extra></extra>" # Hides the default trace info
        ))

        fig.update_traces(marker=dict(size=5, opacity=0.8))

        st.plotly_chart(fig, use_container_width=True)

        st.markdown("Each point represents a text chunk. Hover over points to see the source file and content.")

    else:
        st.warning("Could not generate t-SNE plot.")

elif embeddings_df is not None and embeddings_df.empty:
     st.warning(f"The file {EMBEDDINGS_FILE} was loaded but contained no valid embeddings after processing.")
# If embeddings_df is None, errors are handled in load_embeddings

st.markdown("---")
st.markdown("Modify t-SNE parameters in the sidebar to potentially reveal different structures in the data.")
