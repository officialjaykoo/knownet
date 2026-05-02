from pathlib import Path


PAGE_DIR_NAME = "pages"


def page_storage_dir(data_dir: Path) -> Path:
    return data_dir / PAGE_DIR_NAME
