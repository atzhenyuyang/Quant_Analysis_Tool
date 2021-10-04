import numpy as np
import pandas as pd
import warnings

from vectorbt import _typing as tp
from vectorbt.utils import checks
from vectorbt.utils.decorators import cached_method
from vectorbt.utils.datetime import is_tz_aware, to_timezone
from vectorbt.utils.config import merge_dicts, Config
from vectorbt.base.array_wrapper import ArrayWrapper, Wrapping
from vectorbt.generic.stats_builder import StatsBuilderMixin
from vectorbt.generic.plots_builder import PlotsBuilderMixin
from vectorbt.generic import plotting

__pdoc__ = {}


class symbol_dict(dict):
    """Dict that contains symbols as keys."""
    pass


class MetaData(type(StatsBuilderMixin), type(PlotsBuilderMixin)):
    pass


DataT = tp.TypeVar("DataT", bound="Data")


class Data(Wrapping, StatsBuilderMixin, PlotsBuilderMixin, metaclass=MetaData):
    """Class that downloads, updates, and manages data coming from a data source."""

    def __init__(self,
                 wrapper: ArrayWrapper,
                 data: tp.Data,
                 tz_localize: tp.Optional[tp.TimezoneLike],
                 tz_convert: tp.Optional[tp.TimezoneLike],
                 missing_index: str,
                 missing_columns: str,
                 download_kwargs: dict,
                 **kwargs) -> None:
        Wrapping.__init__(
            self,
            wrapper,
            data=data,
            tz_localize=tz_localize,
            tz_convert=tz_convert,
            missing_index=missing_index,
            missing_columns=missing_columns,
            download_kwargs=download_kwargs,
            **kwargs
        )
        StatsBuilderMixin.__init__(self)
        PlotsBuilderMixin.__init__(self)

        checks.assert_instance_of(data, dict)
        for k, v in data.items():
            checks.assert_meta_equal(v, data[list(data.keys())[0]])
        self._data = data
        self._tz_localize = tz_localize
        self._tz_convert = tz_convert
        self._missing_index = missing_index
        self._missing_columns = missing_columns
        self._download_kwargs = download_kwargs

    def indexing_func(self: DataT, pd_indexing_func: tp.PandasIndexingFunc, **kwargs) -> DataT:
        """Perform indexing on `Data`."""
        new_wrapper = pd_indexing_func(self.wrapper)
        new_data = {k: pd_indexing_func(v) for k, v in self.data.items()}
        return self.replace(
            wrapper=new_wrapper,
            data=new_data
        )

    @property
    def data(self) -> tp.Data:
        """Data dictionary keyed by symbol."""
        return self._data

    @property
    def symbols(self) -> tp.List[tp.Label]:
        """List of symbols."""
        return list(self.data.keys())

    @property
    def tz_localize(self) -> tp.Optional[tp.TimezoneLike]:
        """`tz_localize` initially passed to `Data.download_symbol`."""
        return self._tz_localize

    @property
    def tz_convert(self) -> tp.Optional[tp.TimezoneLike]:
        """`tz_convert` initially passed to `Data.download_symbol`."""
        return self._tz_convert

    @property
    def missing_index(self) -> str:
        """`missing_index` initially passed to `Data.download_symbol`."""
        return self._missing_index

    @property
    def missing_columns(self) -> str:
        """`missing_columns` initially passed to `Data.download_symbol`."""
        return self._missing_columns

    @property
    def download_kwargs(self) -> dict:
        """Keyword arguments initially passed to `Data.download_symbol`."""
        return self._download_kwargs

    @classmethod
    def align_index(cls, data: tp.Data, missing: str = 'nan') -> tp.Data:
        """Align data to have the same index.
        The argument `missing` accepts the following values:
        * 'nan': set missing data points to NaN
        * 'drop': remove missing data points
        * 'raise': raise an error"""
        if len(data) == 1:
            return data

        index = None
        for k, v in data.items():
            if index is None:
                index = v.index
            else:
                if len(index.intersection(v.index)) != len(index.union(v.index)):
                    if missing == 'nan':
                        warnings.warn("Symbols have mismatching index. "
                                      "Setting missing data points to NaN.", stacklevel=2)
                        index = index.union(v.index)
                    elif missing == 'drop':
                        warnings.warn("Symbols have mismatching index. "
                                      "Dropping missing data points.", stacklevel=2)
                        index = index.intersection(v.index)
                    elif missing == 'raise':
                        raise ValueError("Symbols have mismatching index")
                    else:
                        raise ValueError(f"missing='{missing}' is not recognized")

        # reindex
        new_data = {k: v.reindex(index=index) for k, v in data.items()}
        return new_data

    @classmethod
    def align_columns(cls, data: tp.Data, missing: str = 'raise') -> tp.Data:
        """Align data to have the same columns.
        See `Data.align_index` for `missing`."""
        if len(data) == 1:
            return data

        columns = None
        multiple_columns = False
        name_is_none = False
        for k, v in data.items():
            if isinstance(v, pd.Series):
                if v.name is None:
                    name_is_none = True
                v = v.to_frame()
            else:
                multiple_columns = True
            if columns is None:
                columns = v.columns
            else:
                if len(columns.intersection(v.columns)) != len(columns.union(v.columns)):
                    if missing == 'nan':
                        warnings.warn("Symbols have mismatching columns. "
                                      "Setting missing data points to NaN.", stacklevel=2)
                        columns = columns.union(v.columns)
                    elif missing == 'drop':
                        warnings.warn("Symbols have mismatching columns. "
                                      "Dropping missing data points.", stacklevel=2)
                        columns = columns.intersection(v.columns)
                    elif missing == 'raise':
                        raise ValueError("Symbols have mismatching columns")
                    else:
                        raise ValueError(f"missing='{missing}' is not recognized")

        # reindex
        new_data = {}
        for k, v in data.items():
            if isinstance(v, pd.Series):
                v = v.to_frame(name=v.name)
            v = v.reindex(columns=columns)
            if not multiple_columns:
                v = v[columns[0]]
                if name_is_none:
                    v = v.rename(None)
            new_data[k] = v
        return new_data

    @classmethod
    def select_symbol_kwargs(cls, symbol: tp.Label, kwargs: dict) -> dict:
        """Select keyword arguments belonging to `symbol`."""
        _kwargs = dict()
        for k, v in kwargs.items():
            if isinstance(v, symbol_dict):
                if symbol in v:
                    _kwargs[k] = v[symbol]
            else:
                _kwargs[k] = v
        return _kwargs

    @classmethod
    def from_data(cls: tp.Type[DataT],
                  data: tp.Data,
                  tz_localize: tp.Optional[tp.TimezoneLike] = None,
                  tz_convert: tp.Optional[tp.TimezoneLike] = None,
                  missing_index: tp.Optional[str] = None,
                  missing_columns: tp.Optional[str] = None,
                  wrapper_kwargs: tp.KwargsLike = None,
                  **kwargs) -> DataT:
        """Create a new `Data` instance from (aligned) data.
        Args:
            data (dict): Dictionary of array-like objects keyed by symbol.
            tz_localize (timezone_like): If the index is tz-naive, convert to a timezone.
                See `vectorbt.utils.datetime.to_timezone`.
            tz_convert (timezone_like): Convert the index from one timezone to another.
                See `vectorbt.utils.datetime.to_timezone`.
            missing_index (str): See `Data.align_index`.
            missing_columns (str): See `Data.align_columns`.
            wrapper_kwargs (dict): Keyword arguments passed to `vectorbt.base.array_wrapper.ArrayWrapper`.
            **kwargs: Keyword arguments passed to the `__init__` method.
        For defaults, see `data` in `vectorbt._settings.settings`."""
        from vectorbt._settings import settings
        data_cfg = settings['data']

        # Get global defaults
        if tz_localize is None:
            tz_localize = data_cfg['tz_localize']
        if tz_convert is None:
            tz_convert = data_cfg['tz_convert']
        if missing_index is None:
            missing_index = data_cfg['missing_index']
        if missing_columns is None:
            missing_columns = data_cfg['missing_columns']
        if wrapper_kwargs is None:
            wrapper_kwargs = {}

        data = data.copy()
        for k, v in data.items():
            # Convert array to pandas
            if not isinstance(v, (pd.Series, pd.DataFrame)):
                v = np.asarray(v)
                if v.ndim == 1:
                    v = pd.Series(v)
                else:
                    v = pd.DataFrame(v)

            # Perform operations with datetime-like index
            if isinstance(v.index, pd.DatetimeIndex):
                if tz_localize is not None:
                    if not is_tz_aware(v.index):
                        v = v.tz_localize(to_timezone(tz_localize))
                if tz_convert is not None:
                    v = v.tz_convert(to_timezone(tz_convert))
                v.index.freq = v.index.inferred_freq
            data[k] = v

        # Align index and columns
        data = cls.align_index(data, missing=missing_index)
        data = cls.align_columns(data, missing=missing_columns)

        # Create new instance
        symbols = list(data.keys())
        wrapper = ArrayWrapper.from_obj(data[symbols[0]], **wrapper_kwargs)
        return cls(
            wrapper,
            data,
            tz_localize=tz_localize,
            tz_convert=tz_convert,
            missing_index=missing_index,
            missing_columns=missing_columns,
            **kwargs
        )

    @classmethod
    def download_symbol(cls, symbol: tp.Label, **kwargs) -> tp.SeriesFrame:
        """Abstract method to download a symbol."""
        raise NotImplementedError

    @classmethod
    def download(cls: tp.Type[DataT],
                 symbols: tp.Union[tp.Label, tp.Labels],
                 tz_localize: tp.Optional[tp.TimezoneLike] = None,
                 tz_convert: tp.Optional[tp.TimezoneLike] = None,
                 missing_index: tp.Optional[str] = None,
                 missing_columns: tp.Optional[str] = None,
                 wrapper_kwargs: tp.KwargsLike = None,
                 **kwargs) -> DataT:
        """Download data using `Data.download_symbol`.
        Args:
            symbols (hashable or sequence of hashable): One or multiple symbols.
                !!! note
                    Tuple is considered as a single symbol (since hashable).
            tz_localize (any): See `Data.from_data`.
            tz_convert (any): See `Data.from_data`.
            missing_index (str): See `Data.from_data`.
            missing_columns (str): See `Data.from_data`.
            wrapper_kwargs (dict): See `Data.from_data`.
            **kwargs: Passed to `Data.download_symbol`.
                If two symbols require different keyword arguments, pass `symbol_dict` for each argument.
        """
        if checks.is_hashable(symbols):
            symbols = [symbols]
        elif not checks.is_sequence(symbols):
            raise TypeError("Symbols must be either hashable or sequence of hashable")

        data = dict()
        for s in symbols:
            # Select keyword arguments for this symbol
            _kwargs = cls.select_symbol_kwargs(s, kwargs)

            # Download data for this symbol
            data[s] = cls.download_symbol(s, **_kwargs)

        # Create new instance from data
        return cls.from_data(
            data,
            tz_localize=tz_localize,
            tz_convert=tz_convert,
            missing_index=missing_index,
            missing_columns=missing_columns,
            wrapper_kwargs=wrapper_kwargs,
            download_kwargs=kwargs
        )

    def update_symbol(self, symbol: tp.Label, **kwargs) -> tp.SeriesFrame:
        """Abstract method to update a symbol."""
        raise NotImplementedError

    def update(self: DataT, **kwargs) -> DataT:
        """Update the data using `Data.update_symbol`.
        Args:
            **kwargs: Passed to `Data.update_symbol`.
                If two symbols require different keyword arguments, pass `symbol_dict` for each argument.
        !!! note
            Returns a new `Data` instance."""
        new_data = dict()
        for k, v in self.data.items():
            # Select keyword arguments for this symbol
            _kwargs = self.select_symbol_kwargs(k, kwargs)

            # Download new data for this symbol
            new_obj = self.update_symbol(k, **_kwargs)

            # Convert array to pandas
            if not isinstance(new_obj, (pd.Series, pd.DataFrame)):
                new_obj = np.asarray(new_obj)
                index = pd.RangeIndex(
                    start=v.index[-1],
                    stop=v.index[-1] + new_obj.shape[0],
                    step=1
                )
                if new_obj.ndim == 1:
                    new_obj = pd.Series(new_obj, index=index)
                else:
                    new_obj = pd.DataFrame(new_obj, index=index)

            # Perform operations with datetime-like index
            if isinstance(new_obj.index, pd.DatetimeIndex):
                if self.tz_localize is not None:
                    if not is_tz_aware(new_obj.index):
                        new_obj = new_obj.tz_localize(to_timezone(self.tz_localize))
                if self.tz_convert is not None:
                    new_obj = new_obj.tz_convert(to_timezone(self.tz_convert))

            new_data[k] = new_obj

        # Align index and columns
        new_data = self.align_index(new_data, missing=self.missing_index)
        new_data = self.align_columns(new_data, missing=self.missing_columns)

        # Concatenate old and new data
        for k, v in new_data.items():
            if isinstance(self.data[k], pd.Series):
                if isinstance(v, pd.DataFrame):
                    v = v[self.data[k].name]
            else:
                v = v[self.data[k].columns]
            v = pd.concat((self.data[k], v), axis=0)
            v = v[~v.index.duplicated(keep='last')]
            if isinstance(v.index, pd.DatetimeIndex):
                v.index.freq = v.index.inferred_freq
            new_data[k] = v

        # Create new instance
        new_index = new_data[self.symbols[0]].index
        return self.replace(
            wrapper=self.wrapper.replace(index=new_index),
            data=new_data
        )

    @cached_method
    def concat(self, level_name: str = 'symbol') -> tp.Data:
        """Return a dict of Series/DataFrames with symbols as columns, keyed by column name."""
        first_data = self.data[self.symbols[0]]
        index = first_data.index
        if isinstance(first_data, pd.Series):
            columns = pd.Index([first_data.name])
        else:
            columns = first_data.columns
        if len(self.symbols) > 1:
            new_data = {c: pd.DataFrame(
                index=index,
                columns=pd.Index(self.symbols, name=level_name)
            ) for c in columns}
        else:
            new_data = {c: pd.Series(
                index=index,
                name=self.symbols[0]
            ) for c in columns}
        for c in columns:
            for s in self.symbols:
                if isinstance(self.data[s], pd.Series):
                    col_data = self.data[s]
                else:
                    col_data = self.data[s][c]
                if len(self.symbols) > 1:
                    new_data[c].loc[:, s] = col_data
                else:
                    new_data[c].loc[:] = col_data

        return new_data

    def get(self, column: tp.Optional[tp.Label] = None, **kwargs) -> tp.MaybeTuple[tp.SeriesFrame]:
        """Get column data.
        If one symbol, returns data for that symbol.
        If multiple symbols, performs concatenation first and returns a DataFrame if one column
        and a tuple of DataFrames if a list of columns passed."""
        if len(self.symbols) == 1:
            if column is None:
                return self.data[self.symbols[0]]
            return self.data[self.symbols[0]][column]

        concat_data = self.concat(**kwargs)
        if len(concat_data) == 1:
            return tuple(concat_data.values())[0]
        if column is not None:
            if isinstance(column, list):
                return tuple([concat_data[c] for c in column])
            return concat_data[column]
        return tuple(concat_data.values())

    # ############# Stats ############# #

    @property
    def stats_defaults(self) -> tp.Kwargs:
        """Defaults for `Data.stats`.
        Merges `vectorbt.generic.stats_builder.StatsBuilderMixin.stats_defaults` and
        `data.stats` from `vectorbt._settings.settings`."""
        from vectorbt._settings import settings
        data_stats_cfg = settings['data']['stats']

        return merge_dicts(
            StatsBuilderMixin.stats_defaults.__get__(self),
            data_stats_cfg
        )

    _metrics: tp.ClassVar[Config] = Config(
        dict(
            start=dict(
                title='Start',
                calc_func=lambda self: self.wrapper.index[0],
                agg_func=None,
                tags='wrapper'
            ),
            end=dict(
                title='End',
                calc_func=lambda self: self.wrapper.index[-1],
                agg_func=None,
                tags='wrapper'
            ),
            period=dict(
                title='Period',
                calc_func=lambda self: len(self.wrapper.index),
                apply_to_timedelta=True,
                agg_func=None,
                tags='wrapper'
            ),
            total_symbols=dict(
                title='Total Symbols',
                calc_func=lambda self: len(self.symbols),
                agg_func=None,
                tags='data'
            ),
            null_counts=dict(
                title='Null Counts',
                calc_func=lambda self, group_by:
                {
                    k: v.isnull().vbt(wrapper=self.wrapper).sum(group_by=group_by)
                    for k, v in self.data.items()
                },
                tags='data'
            )
        ),
        copy_kwargs=dict(copy_mode='deep')
    )

    @property
    def metrics(self) -> Config:
        return self._metrics

    # ############# Plotting ############# #

    def plot(self,
             column: tp.Optional[tp.Label] = None,
             base: tp.Optional[float] = None,
             **kwargs) -> tp.Union[tp.BaseFigure, plotting.Scatter]:  # pragma: no cover
        """Plot orders.
        Args:
            column (str): Name of the column to plot.
            base (float): Rebase all series of a column to a given intial base.
                !!! note
                    The column should contain prices.
            kwargs (dict): Keyword arguments passed to `vectorbt.generic.accessors.GenericAccessor.plot`.
        ## Example
        ```python-repl
        >>> import vectorbt as vbt
        >>> start = '2021-01-01 UTC'  # crypto is in UTC
        >>> end = '2021-06-01 UTC'
        >>> data = vbt.YFData.download(['BTC-USD', 'ETH-USD', 'ADA-USD'], start=start, end=end)
        >>> data.plot(column='Close', base=1)
        ```
        ![](/docs/img/data_plot.svg)"""
        self_col = self.select_one(column=column, group_by=False)
        data = self_col.get()
        if base is not None:
            data = data.vbt.rebase(base)
        return data.vbt.plot(**kwargs)

    @property
    def plots_defaults(self) -> tp.Kwargs:
        """Defaults for `Data.plots`.
        Merges `vectorbt.generic.plots_builder.PlotsBuilderMixin.plots_defaults` and
        `data.plots` from `vectorbt._settings.settings`."""
        from vectorbt._settings import settings
        data_plots_cfg = settings['data']['plots']

        return merge_dicts(
            PlotsBuilderMixin.plots_defaults.__get__(self),
            data_plots_cfg
        )

    _subplots: tp.ClassVar[Config] = Config(
        dict(
            plot=dict(
                check_is_not_grouped=True,
                plot_func='plot',
                pass_add_trace_kwargs=True,
                tags='data'
            )
        ),
        copy_kwargs=dict(copy_mode='deep')
    )

    @property
    def subplots(self) -> Config:
        return self._subplots


Data.override_metrics_doc(__pdoc__)
Data.override_subplots_doc(__pdoc__)
