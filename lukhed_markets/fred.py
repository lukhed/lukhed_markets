from lukhed_basic_utils.classCommon import LukhedAuth
from fredapi import Fred
import pandas as pd
from lukhed_basic_utils import timeCommon as tC
from lukhed_basic_utils import osCommon as osC
from lukhed_basic_utils import fileCommon as fC

class FRED(LukhedAuth):
    """
    FRED class for accessing Federal Reserve Economic Data (FRED) API.
    
    This class is a simple wrapper around https://github.com/mortada/fredapi, with additional methods and 
    key management via LukhedAuth.
    """

    def __init__(self, key_management='github', provide_key=None):
        """
        Initialize the FRED class with authentication.

        Parameters
        ----------
        key_management : str, optional
            Key management strategy ('default', 'local', etc.), by default 'github'
        """
        if provide_key:
            self._auth_data = {
                "key": provide_key
            }
        else:
            super().__init__('fred', key_management=key_management)

        self.base_url = "https://api.stlouisfed.org/fred"

        if self._auth_data is None:
            print("No existing FRED API key data found, starting setup...")
            self._fred_setup()

        self.api = Fred(api_key=self._auth_data['key'])

    def _fred_setup(self):
        """
        Setup method for FRED API key management.
        """
        print("\n\n***********************************\n" \
        "This is the lukhed setup for FRED.\nIf you haven't already, you first need a FRED api key.\n" \
        "You can sign up for a free developer account here: https://fred.stlouisfed.org/docs/api/fred/\n\n")
            
        if input("Do you have your API key and are ready to continue (y/n)?") == 'n':
            print("OK, come back when you have an api key.")
            quit()

        fred_key = input("Paste your api key here (found in FRED API keys section "
                               "https://fredaccount.stlouisfed.org/apikeys):\n").replace(" ", "")
        self._auth_data = {
            "key": fred_key
        }
        self.kM.force_update_key_data(self._auth_data)
        print("Setup complete!")

    def _parse_dates(self, start_date, end_date, date_format):
        """
        Parse and format start and end dates.

        Parameters
        ----------
        start_date : str
            Start date as a string.
        end_date : str
            End date as a string.
        date_format : str
            Format of the input date strings.

        Returns
        -------
        tuple
            Formatted start and end dates as strings.
        """
        strt = tC.convert_date_format(start_date, from_format=date_format, to_format="%Y-%m-%d") if start_date else None
        end = tC.convert_date_format(end_date, from_format=date_format, to_format="%Y-%m-%d") if end_date else None

        return strt, end
    
    def _save_plot(self, plt, plot_name):
        """
        Save the plot to a file.

        Parameters
        ----------
        plt : matplotlib.pyplot
            The plot object to save.
        plot_name : str
            The name of the plot file.
        """

        osC.check_create_dir_structure(['plots'])
        plot_path = osC.create_file_path_string(['plots', plot_name])
        plt.savefig(plot_path)
        print(f"Plot saved to {plot_path}")

    def get_pce_inflation_rate(self, start_date=None, end_date=None, date_format='%Y-%m-%d'):
        """
        Get the pce inflation series with the year over year inflation rate calculated and added to the dataframe
        https://fred.stlouisfed.org/data/PCEPI

        The Personal Consumption Expenditures Price Index is a measure of the prices that people living in the 
        United States, or those buying on their behalf, pay for goods and services. The change in the PCE price 
        index is known for capturing inflation (or deflation) across a wide range of consumer expenses and reflecting 
        changes in consumer behavior.

        The PCE Price index is the Federal Reserve’s preferred measure of inflation. The PCE Price Index is similar 
        to the Bureau of Labor Statistics' consumer price index for urban consumers. The two indexes, which have their 
        own purposes and uses, are constructed differently, resulting in different inflation rates.

        Parameters
        ----------
        start_date : str, optional
            Start date for the data in 'YYYY-MM-DD' format, by default None (earliest available)
        end_date : str, optional
            End date for the data in 'YYYY-MM-DD' format, by default None (latest available)
        date_format : str, optional
            Date format for start_date and end_date, by default '%Y-%m-%d'

        Returns
        -------
        pandas.DataFrame
            DataFrame containing PCE data with YoY inflation rate.
        """

        start_date, end_date = self._parse_dates(start_date, end_date, date_format)
        series = self.api.get_series('PCEPI', observation_start=start_date, observation_end=end_date)
        
        # Convert to DataFrame
        df = pd.DataFrame(series, columns=['PCEPI'])
        
        # Ensure index is datetime and sorted
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        # Calculate year-over-year inflation rate
        df['yoy_inflation'] = df['PCEPI'].pct_change(12) * 100

        return df
    
    def get_manufacturing_employees(self, start_date=None, end_date=None, date_format='%Y-%m-%d'):
        """
        Get the manufacturing employees series data.
        https://fred.stlouisfed.org/series/MANEMP

        Manufacturing employment measures the number of wage and salary workers in the manufacturing sector. 
        This series is a good indicator of the health of the manufacturing industry and overall economic activity.

        Parameters
        ----------
        start_date : str, optional
            Start date for the data in 'YYYY-MM-DD' format, by default None (earliest available)
        end_date : str, optional
            End date for the data in 'YYYY-MM-DD' format, by default None (latest available)
        date_format : str, optional
            Date format for start_date and end_date, by default '%Y-%m-%d'

        Returns
        -------
        pandas.DataFrame
            DataFrame containing manufacturing employment data.
        """

        start_date, end_date = self._parse_dates(start_date, end_date, date_format)
        series = self.api.get_series('MANEMP', observation_start=start_date, observation_end=end_date)
        
        # Convert to DataFrame
        df = pd.DataFrame(series, columns=['Manufacturing_Employees'])
        
        # Ensure index is datetime and sorted
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        return df
    
    def federal_governemnt_interest_payments_to_row(self, start_date=None, end_date=None, date_format='%Y-%m-%d'):
        """
        Get the federal government interest payments to the rest of the world series data.
        https://fred.stlouisfed.org/series/B093RC1Q027SBEA

        Parameters
        ----------
        start_date : str, optional
            Start date for the data in 'YYYY-MM-DD' format, by default None
        end_date : str, optional
            End date for the data in 'YYYY-MM-DD' format, by default None
        date_format : str, optional
            Date format for start_date and end_date, by default '%Y-%m-%d'

        Returns
        -------
        pandas.DataFrame
            DataFrame containing federal government interest payments to the rest of the world data.
        """

        start_date, end_date = self._parse_dates(start_date, end_date, date_format)
        series = self.api.get_series('B093RC1Q027SBEA', observation_start=start_date, observation_end=end_date)
        
        # Convert to DataFrame
        df = pd.DataFrame(series, columns=['Fed_Govt_Interest_Payments_to_ROW'])
        
        # Ensure index is datetime and sorted
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        return df
    
    def plot_pce_inflation_rate(self, start_date=None, end_date=None, date_format='%Y-%m-%d', 
                                include_averages=True, show_plot=True, save_plots=False):
        """
        Plot the PCE inflation rate over time.

        Parameters
        ----------
        start_date : str, optional
            Start date for the data in 'YYYY-MM-DD' format, by default None
        end_date : str, optional
            End date for the data in 'YYYY-MM-DD' format, by default None
        date_format : str, optional
            Date format for start_date and end_date, by default '%Y-%m-%d'
        include_averages : bool, optional
            Whether to include average target and average inflation lines, by default True
            **The Fed's long-term target for inflation is 2 percent annual increase in the PCE Price Index.**
        save_plots : bool, optional
            Whether to save the plots as PNG files, by default False
            **Saved plots will be stored in a 'plots' directory.**
        show_plot : bool, optional
            Whether to display the plot, by default True

        Returns
        -------
        None
        """
        
        import matplotlib.pyplot as plt

        # First substract 1 year from start date to ensure we have data for YoY calculation
        start_date, end_date = self._parse_dates(start_date, end_date, date_format)
        if start_date:
            start_date = tC.add_days_to_date(start_date, -365, input_format="%Y-%m-%d", ouput_format="%Y-%m-%d")

        df = self.get_pce_inflation_rate(start_date, end_date, date_format="%Y-%m-%d")

        # Now remove all NaN values that were created due to YoY calculation
        df = df.dropna(subset=['yoy_inflation'])

        # Plotting
        plt.figure(figsize=(10, 6))
        plt.plot(df.index, df['yoy_inflation'], label='PCE YoY Inflation Rate', color='blue')
        # add total years calculation to title
        total_years = (df.index[-1] - df.index[0]).days / 365.25
        plot_title = f"PCE Year-over-Year Inflation Rate ({total_years:.1f} years)"
        plt.title(plot_title)
        plt.xlabel('Date')
        plt.ylabel('Inflation Rate (%)')
        # bold 0 line
        plt.axhline(0, color='black', linewidth=0.8, linestyle='-')
        if include_averages:
            avg_inflation = df['yoy_inflation'].mean()
            plt.axhline(2, color='red', linewidth=0.8, linestyle='--', label='Fed Target (2%)')
            plt.axhline(avg_inflation, color='green', linewidth=0.8, linestyle='--', 
                        label=f'Average Inflation ({avg_inflation:.2f}%)')
        plt.legend()
        plt.grid(True)

        if show_plot:
            plt.show()

        if save_plots:
            plot_name = f"pce_inflation_{start_date}_to_{end_date}.png"
            self._save_plot(plt, plot_name)
    
