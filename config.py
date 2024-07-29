#####################################################################################################################
# Description:
# The config.py module defines the configuration settings and constants .
# It encapsulates environment variables, URL endpoints, and other configuration variables.
# The Config class provides methods to access these settings.
# The module also includes validation for required environment variables.
#####################################################################################################################
import os

class Config:
    REQUIRED_ENV_VARS = ["COGNITO_LOCALHOST_CLIENT_SECRET", "COGNITO_PROD_CLIENT_SECRET"]

    @staticmethod
    def check_required_env_vars():
        for env_var in Config.REQUIRED_ENV_VARS:
            if not os.getenv(env_var):
                raise ValueError(f"Please set the {env_var} environment variable")

    # Define your configuration values
    IS_DEVELOPER_VIEW = True
    ON_LOCALHOST = False
    MCM_URL = "https://classification.dilab-ivy.com/ivy/ask_question"
    SKILL_NAME_TO_MCM_URL = {
        "Classification": "https://classification.dilab-ivy.com/ivy/ask_question",
        "Incremental Concept Learning": "https://icl.dilab-ivy.com/ivy/ask_question",
        "Means End Analysis": "https://mea.dilab-ivy.com/ivy/ask_question",
        "Semantic Networks": "https://gpp.dilab-ivy.com/ivy/ask_question",
    }
    COGNITO_DOMAIN = "https://ivy.auth.us-east-1.amazoncognito.com"
    URL_CODE = ""
    ACCESS_TOKEN = ""
    REDIRECT_URL = (
        "http://localhost:8002/ask-ivy"
        if ON_LOCALHOST
        else "https://dev.dilab-ivy.com/ask-ivy"
    )
    CLIENT_ID = (
        "60p8a9bvteiihrd8g89r5ggabi" if ON_LOCALHOST else "2d7ah9kttong2hdlt4olhtao4d"
    )
    CLIENT_SECRET = (
        os.getenv("COGNITO_LOCALHOST_CLIENT_SECRET")
        if ON_LOCALHOST
        else os.getenv("COGNITO_PROD_CLIENT_SECRET")
    )
    LOGIN_URL = (
        COGNITO_DOMAIN
        + f"/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URL}"
    )
    GET_ACCESS_TOKEN_URL = COGNITO_DOMAIN + "/oauth2/token"
    GET_USER_INFO_URL = COGNITO_DOMAIN + "/oauth2/userInfo"
    USER_NAME = ""
    USERNAME = ""
    USER_EMAIL = ""

# Check environment variables
Config.check_required_env_vars()
