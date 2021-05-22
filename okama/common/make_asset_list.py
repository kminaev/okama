from typing import Dict, Optional, List, Any, Type, Union

import numpy as np
import pandas as pd

from .validators import validate_integer
from ..macro import Inflation
from ..asset import Asset
from ..settings import default_ticker, PeriodLength, _MONTHS_PER_YEAR


class ListMaker:
    def __init__(
        self,
        assets: Optional[List[Union[str, Type]]] = None,
        *,
        first_date: Optional[str] = None,
        last_date: Optional[str] = None,
        ccy: str = "USD",
        inflation: bool = True,
    ):
        self._assets = assets
        self._currency = Asset(symbol=f"{ccy}.FX")
        (
            self.first_date,
            self.last_date,
            self.newest_asset,
            self.eldest_asset,
            self.names,
            self.currencies,
            self.assets_first_dates,
            self.assets_last_dates,
            self.assets_ror,
        ) = self.make_list(ls=self.assets).values()
        if inflation:
            self.inflation: str = f"{ccy}.INFL"
            self._inflation_instance: Inflation = Inflation(
                self.inflation, self.first_date, self.last_date
            )
            self.inflation_ts: pd.Series = self._inflation_instance.values_ts
            self.inflation_first_date: pd.Timestamp = self._inflation_instance.first_date
            self.inflation_last_date: pd.Timestamp = self._inflation_instance.last_date
            self.first_date = max(self.first_date, self.inflation_first_date)
            self.last_date: pd.Timestamp = min(self.last_date, self.inflation_last_date)
            # Add inflation to the date range dict
            self.assets_first_dates.update({self.inflation: self.inflation_first_date})
            self.assets_last_dates.update({self.inflation: self.inflation_last_date})
        if first_date:
            self.first_date = max(self.first_date, pd.to_datetime(first_date))
        self.assets_ror = self.assets_ror[self.first_date :]
        if last_date:
            self.last_date = min(self.last_date, pd.to_datetime(last_date))
        self.assets_ror: pd.DataFrame = self.assets_ror[
            self.first_date : self.last_date
        ]
        self.period_length: float = round(
            (self.last_date - self.first_date) / np.timedelta64(365, "D"), ndigits=1
        )
        self.pl = PeriodLength(
            self.assets_ror.shape[0] // _MONTHS_PER_YEAR,
            self.assets_ror.shape[0] % _MONTHS_PER_YEAR,
        )
        self._pl_txt = f"{self.pl.years} years, {self.pl.months} months"
        self._dividend_yield: pd.DataFrame = pd.DataFrame(dtype=float)
        self._dividends_ts: pd.DataFrame = pd.DataFrame(dtype=float)

    def __repr__(self):
        dic = {
            "symbols": self.symbols,
            "currency": self._currency.ticker,
            "first_date": self.first_date.strftime("%Y-%m"),
            "last_date": self.last_date.strftime("%Y-%m"),
            "period_length": self._pl_txt,
            "inflation": self.inflation if hasattr(self, "inflation") else "None",
        }
        return repr(pd.Series(dic))

    def __len__(self):
        return len(self.symbols)

    @staticmethod
    def define_symbol_list(assets):
        return [asset.symbol if hasattr(asset, 'symbol') else asset for asset in assets]

    def _add_inflation(self) -> pd.DataFrame:
        """
        Add inflation column to returns DataFrame.
        """
        if hasattr(self, "inflation"):
            return pd.concat(
                [self.assets_ror, self.inflation_ts], axis=1, join="inner", copy="false"
            )
        else:
            return self.assets_ror

    def _remove_inflation(self, time_frame: int) -> pd.DataFrame:
        """
        Remove inflation column from rolling returns if exists.
        """
        if hasattr(self, "inflation"):
            return self.get_rolling_cumulative_return(window=time_frame).drop(
                columns=[self.inflation]
            )
        else:
            return self.get_rolling_cumulative_return(window=time_frame)

    def _validate_period(self, period: Any) -> None:
        """
        Check if conditions are met:
        * period should be an integer
        * period should be positive
        * period should not exceed history period length

        Parameters
        ----------
        period : Any

        Returns
        -------
        None
            No exceptions raised if validation passes.
        """
        validate_integer("period", period, min_value=0, inclusive=False)
        if period > self.pl.years:
            raise ValueError(
                f"'period' ({period}) is beyond historical data range ({self.period_length})."
            )

    @property
    def assets(self):
        assets = [default_ticker] if not self._assets else self._assets
        if not isinstance(assets, list):
            raise ValueError("Assets must be a list.")
        return assets

    @property
    def symbols(self) -> List[str]:
        """
        Return a list of financial symbols used to set the AssetList.

        Symbols are similar to tickers but have a namespace information:

        * SPY.US is a symbol
        * SPY is a ticker

        Returns
        -------
        list of str
            List of symbols included in the Asset List.
        """
        return self.define_symbol_list(self.assets)

    @property
    def tickers(self) -> List[str]:
        """
        Return a list of tickers (symbols without a namespace) used to set the AssetList.

        tickers are similar to symbols but do not have namespace information:

        * SPY is a ticker
        * SPY.US is a symbol

        Returns
        -------
        list of str
            List of tickers included in the Asset List.
        """
        return [x.split(".", 1)[0] for x in self.symbols]

    @property
    def currency(self) -> str:
        """
        Return the base currency of the Asset List.

        Such properties as rate of return and risk are adjusted to the base currency.

        Returns
        -------
        okama.Asset
            Base currency of the Asset List in form of okama.Asset class.
        """
        return self._currency.currency

    def make_list(self, ls: list) -> dict:
        """
        Make an asset list from a list of symbols.
        """
        currency_name: str = self._currency.name
        currency_first_date: pd.Timestamp = self._currency.first_date
        currency_last_date: pd.Timestamp = self._currency.last_date

        first_dates: Dict[str, pd.Timestamp] = {}
        last_dates: Dict[str, pd.Timestamp] = {}
        names: Dict[str, str] = {}
        currencies: Dict[str, str] = {}
        df = pd.DataFrame()
        for i, x in enumerate(ls):
            asset = x if hasattr(x, 'symbol') and hasattr(x, 'ror') else Asset(x)
            if i == 0:  # required to use pd.concat below (df should not be empty).
                df = self.make_ror(asset, currency_name)
            else:
                new = self.make_ror(asset, currency_name)
                df = pd.concat([df, new], axis=1, join="inner", copy="false")
            currencies.update({asset.symbol: asset.currency})
            names.update({asset.symbol: asset.name})
            first_dates.update({asset.symbol: asset.first_date})
            last_dates.update({asset.symbol: asset.last_date})
        # Add currency to the date range dict
        first_dates.update({currency_name: currency_first_date})
        last_dates.update({currency_name: currency_last_date})
        currencies.update({"asset list": currency_name})

        first_dates_sorted: list = sorted(first_dates.items(), key=lambda y: y[1])
        last_dates_sorted: list = sorted(last_dates.items(), key=lambda y: y[1])
        if isinstance(df, pd.Series):
            df = (
                df.to_frame()
            )  # required to convert Series to DataFrame for single asset list
        return dict(
            first_date=first_dates_sorted[-1][1],
            last_date=last_dates_sorted[0][1],
            newest_asset=first_dates_sorted[-1][0],
            eldest_asset=first_dates_sorted[0][0],
            names_dict=names,
            currencies_dict=currencies,
            assets_first_dates=dict(first_dates_sorted),
            assets_last_dates=dict(last_dates_sorted),
            ror=df,
        )

    def make_ror(self, asset, currency_name):
        return (
            asset.ror
            if asset.currency == currency_name
            else self.set_currency(
                returns=asset.ror,
                asset_currency=asset.currency,
                list_currency=currency_name,
            )
        )

    @classmethod
    def set_currency(
        cls, returns: pd.Series, asset_currency: str, list_currency: str
    ) -> pd.Series:
        """
        Set return to a certain currency.
        """
        currency = Asset(symbol=f"{asset_currency}{list_currency}.FX")
        asset_mult = returns + 1.0
        currency_mult = currency.ror + 1.0
        # join dataframes to have the same Time Series Index
        df = pd.concat([asset_mult, currency_mult], axis=1, join="inner", copy="false")
        currency_mult = df.iloc[:, -1]
        asset_mult = df.iloc[:, 0]
        x = asset_mult * currency_mult - 1.0
        x.rename(returns.name, inplace=True)
        return x
