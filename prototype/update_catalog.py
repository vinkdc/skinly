import sys

from skin_catalog import CatalogError, CATALOG_PATH, fetch_catalog, save_catalog


def main():
    try:
        catalog = fetch_catalog()
        save_catalog(catalog)
    except CatalogError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    assigned = sum(entry["weapon"] is not None for entry in catalog)
    print(f"Catalog updated: {len(catalog)} skins")
    print(f"Weapon assigned: {assigned}")
    print(f"Weapon unknown: {len(catalog) - assigned}")
    print(f"Cache: {CATALOG_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
