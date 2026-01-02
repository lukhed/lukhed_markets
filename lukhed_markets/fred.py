from lukhed_basic_utils.classCommon import LukhedAuth

class FRED(LukhedAuth):
    """
    FRED class for accessing Federal Reserve Economic Data (FRED) API.

    Inherits from LukhedAuth for authentication handling.
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
