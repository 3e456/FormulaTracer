import xarray as xr

from components.model import calculate_weighted_score


def write_result(quantity, factor):
    weighted_score = calculate_weighted_score(quantity, factor)
    dataset = xr.Dataset()
    dataset["weighted_score"] = weighted_score
    dataset.to_netcdf("result.nc")
