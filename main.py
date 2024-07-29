import time
from datetime import datetime, timezone

import gradio as gr
import httpx
import requests
import base64
import uvicorn

from fastapi import FastAPI
from starlette.responses import RedirectResponse

from chat_logging import (
    log_chat_history,
    generate_csv
)

from config import Config
Config.check_required_env_vars()

# Use configuration values
IS_DEVELOPER_VIEW = Config.IS_DEVELOPER_VIEW
ON_LOCALHOST = Config.ON_LOCALHOST
MCM_URL = Config.MCM_URL
SKILL_NAME_TO_MCM_URL = Config.SKILL_NAME_TO_MCM_URL
COGNITO_DOMAIN = Config.COGNITO_DOMAIN
URL_CODE = Config.URL_CODE
ACCESS_TOKEN = Config.ACCESS_TOKEN
REDIRECT_URL = Config.REDIRECT_URL
CLIENT_ID = Config.CLIENT_ID
CLIENT_SECRET = Config.CLIENT_SECRET
LOGIN_URL = Config.LOGIN_URL
GET_ACCESS_TOKEN_URL = Config.GET_ACCESS_TOKEN_URL
GET_USER_INFO_URL = Config.GET_USER_INFO_URL
USER_NAME = Config.USER_NAME
USERNAME = Config.USERNAME
USER_EMAIL = Config.USER_EMAIL

app = FastAPI()


@app.get("/")
def read_main():
    return RedirectResponse(url=LOGIN_URL)


def get_access_token_and_user_info(url_code):
    global URL_CODE
    URL_CODE = url_code
    access_token_data = {
        "grant_type": "authorization_code",
        "client_id": Config.CLIENT_ID,
        "code": URL_CODE,
        "redirect_uri": Config.REDIRECT_URL,
    }
    access_token_headers = {
        "Authorization": "Basic "
        + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode("ascii")).decode(
            "ascii"
        ),
        "Content-Type": "application/x-www-form-urlencoded",
    }

    def get_user_info_header(access_token):
        return {
            "Authorization": "Bearer " + access_token,
            "Content-Type": "application/x-amz-json-1.1",
        }

    try:
        # Get Access Token
        response = requests.post(
            Config.GET_ACCESS_TOKEN_URL, data=access_token_data, headers=access_token_headers
        )
        access_token = response.json()["access_token"]
        Config.ACCESS_TOKEN = access_token

        # Get User Info
        response = requests.get(
            Config.GET_USER_INFO_URL, headers=get_user_info_header(access_token)
        ).json()
        Config.USER_NAME = response["name"]
        Config.USERNAME = response["username"]
        Config.USER_EMAIL = response["email"]
        return True
    except Exception as e:
        print(str(e))
        return False


# Sends a POST request to the MCM, Returns response
def get_mcm_response(question: str) -> str:
    try:
        response = httpx.post(
            Config.MCM_URL,
            json={"question": question, "api_key": mcm_api_key.value, "Episodic_Knowledge": {}},
            timeout=timeout_secs.value,
        )
        return response.json().get("response", "")
    except httpx.RequestError as e:
        print(f"HTTP request failed: {e}")
        return ""

# Gradio Interface Setup
with gr.Blocks() as ivy_main_page:
    # Title
    welcome_msg = gr.Markdown()
    # Settings
    with gr.Row():
        mcm_skill = gr.Dropdown(
            choices=SKILL_NAME_TO_MCM_URL.keys(),
            value="Classification",
            multiselect=False,
            label="Skill",
            interactive=True,
        )
        with gr.Accordion("Settings", open=False, visible=IS_DEVELOPER_VIEW):
            # MCM Settings
            with gr.Group("MCM Settings"):
                with gr.Row():
                    # MCM API Key
                    mcm_api_key = gr.Textbox(
                        value="123456789",
                        label="MCM API Key",
                        interactive=True,
                    )
                    timeout_secs = gr.Slider(
                        label="Timeout (seconds)",
                        minimum=5,
                        maximum=300,
                        step=5,
                        value=60,
                        interactive=True,
                    )

    chatbot = gr.Chatbot(
        label="Your Conversation",
        show_copy_button=True,
        placeholder="Your conversations will appear here...",
    )
    msg = gr.Textbox(
        label="Question",
        placeholder="Please enter your question here...",
        show_copy_button=True,
        autofocus=True,
        show_label=True,
    )
    with gr.Row():
        submit = gr.Button(value="Submit", variant="primary")
        clear = gr.Button(value="Clear", variant="stop")
    with gr.Row():
        flag_btn = gr.Button(
            value="Flag last response", variant="secondary", visible=IS_DEVELOPER_VIEW
        )
        download_btn = gr.DownloadButton(
            value="Download Flagged Responses", variant="secondary", visible=IS_DEVELOPER_VIEW
        )

    def on_page_load(request: gr.Request):
        if "code" not in dict(request.query_params):
            # (TODO): Redirect to login page
            return "Go back to login page"
        url_code = dict(request.query_params)["code"]
        if not get_access_token_and_user_info(url_code):
            # (TODO): Redirect to Login page or display Error page
            return "An Error Occurred"
        return f"# Welcome to Ivy Chatbot, {Config.USERNAME}"

    
    def update_user_message(user_message, history):
        return "", history + [[user_message, None]]

    def get_response_from_ivy(history):
        history[-1][1] = ""
        response = get_mcm_response(history[-1][0])
        for character in response:
            history[-1][1] += character
            time.sleep(0.005)
            yield history
        # Log to DynamoDB every interaction here
        log_chat_history(
            Config.USERNAME, Config.ACCESS_TOKEN, history[-1][0], history[-1][1], "no_reaction"
        )

    def log_commended_response(history):
        if len(history) == 0:
            return
        response = history[-1][1]
        question = history[-1][0]
        log_chat_history(Config.USERNAME, Config.ACCESS_TOKEN, question, response, "liked")
        gr.Info("Saved successfully!")

    def log_disliked_response(history):
        if len(history) == 0:
            return
        response = history[-1][1]
        question = history[-1][0]
        log_chat_history(Config.USERNAME, Config.ACCESS_TOKEN, question, response, "disliked")
        gr.Info("Saved successfully!")

    def log_flagged_response(history):
        if len(history) == 0:
            return
        response = history[-1][1]
        question = history[-1][0]
        log_chat_history(Config.USERNAME, Config.ACCESS_TOKEN, question, response, "flagged")
        gr.Info("Saved successfully!")

    def chat_liked_or_disliked(history, data: gr.LikeData):
        question = history[data.index[0]][0]
        response = history[data.index[0]][1]
        if data.liked:
            log_commended_response([[question, response]])
        else:
            log_disliked_response([[question, response]])

    def handle_download_click():
        filepath = generate_csv(Config.USERNAME, Config.ACCESS_TOKEN)
        return filepath if filepath else None

    def update_skill(skill_name):
        Config.MCM_URL = Config.SKILL_NAME_TO_MCM_URL[skill_name]
        return []

    ivy_main_page.load(on_page_load, None, [welcome_msg])
    mcm_skill.change(update_skill, [mcm_skill], [chatbot])
    msg.submit(
        update_user_message, [msg, chatbot], [msg, chatbot], queue=False
    ).success(get_response_from_ivy, chatbot, chatbot)
    submit.click(
        update_user_message, [msg, chatbot], [msg, chatbot], queue=False
    ).success(get_response_from_ivy, chatbot, chatbot)
    chatbot.like(chat_liked_or_disliked, chatbot, None)
    clear.click(lambda: None, None, chatbot, queue=False)
    flag_btn.click(log_flagged_response, chatbot, None)
    download_btn.click(
        handle_download_click,
        inputs=[],
        outputs=[download_btn],
    )

# Launch the Application
ivy_main_page.queue()

with gr.Blocks() as evaluation_page:
    # Develop Evaluation page
    # Placeholder interface
    gr.Interface(lambda x: f"Hello {x}!", inputs="text", outputs="text")

app = gr.mount_gradio_app(app, ivy_main_page, path="/ask-ivy", root_path="/ask-ivy")
app = gr.mount_gradio_app(
    app, evaluation_page, path="/evaluation", root_path="/evaluation"
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)