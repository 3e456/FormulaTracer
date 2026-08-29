# Scientific library / Provider

provider entryは、選択されたAPI contractまたはreference classificationがあることを
意味します。library全API、全dtype、全backend/device/default/versionの対応を意味しません。

主要harvest registryはPython builtins、NumPy、SciPy、pandas、xarray、Dask、GeoPandas、
Shapely、pyproj、Rasterio、netCDF4、igraphの12 familyです。ecosystem registryには、現行の
versioned dataに記録されたJAX/PyTorch/CuPy/Numba/SymPy/scikit-learn/statsmodels、
Rust scientific crates、Eigen/Boost等の選択contractもあります。

registryの`version`はreference harvest範囲であり、release全体のcompatibility保証ではありません。
現在の公開support designationは`REFERENCE_ONLY_VERSION_UNPINNED`です。正式なversion範囲は、
signature/default/axis/dimension/dtype/欠損値/mutation/lazy/device/数学semanticの照合後に定めます。

現行inventoryはpublic API 14,864、contract target 9,350、formalized/classified 9,207、
not applicable 139、reference insufficient 4、existing formal contract 393、contract object 2,136です。
これはinventory/classification数であり、個別Lean proof数やlibrary全体対応数ではありません。
