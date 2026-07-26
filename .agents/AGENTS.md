# Project Rules & Guidelines

## Environment Dependency Verification & Native ML Fallbacks
- **Check Installed Packages**: Before generating or executing data analysis scripts, inspect the active virtual environment (`.venv\Scripts\pip.exe list`) to confirm which libraries are available.
- **Prefer Native Implementations**: If specialized packages (e.g. `scikit-learn`, `scipy`) are not installed, prefer native `numpy` and `pandas` vector mathematics (e.g., SVD for PCA, Euclidean matrix distance for K-Means) to maintain zero-dependency reliability without modifying the user's environment unless requested.
