import os
import pathlib
import time
from datetime import datetime, timezone

import gradio as gr
import httpx
import boto3
import requests
import base64
import csv
import tempfile
import uvicorn

from fastapi import FastAPI
from starlette.responses import RedirectResponse

REQUIRED_ENV_VARS = ["COGNITO_LOCALHOST_CLIENT_SECRET", "COGNITO_PROD_CLIENT_SECRET"]
for env_var in REQUIRED_ENV_VARS:
    if not os.getenv(env_var):
        raise ValueError(f"Please set the {env_var} environment variable")

# If is_developer_view is True then there's additional functionalities available.
IS_DEVELOPER_VIEW = True
ON_LOCALHOST = False
MCM_SKILL = "Classification"
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

EVALUATION_QUESTIONS = []
EVALUATION_QUESTION_NUM = 0
EVALUATION_METRIC_DESCRIPTION = {
    "Correctness": "A response with high correctness should be factually accurate (based on TMK) to the question or context",
    "Completeness": "A response with high completeness satisfactorily covers all aspects of a user’s query, ensuring no critical information is left out",
    "Confidence": "A response with high confidence is indicated by straightforward, factual answers, while terms like 'not sure,' 'likely,' or 'could be' signify medium to low confidence",
    "Comprehensibility": "A response with high comprehensibility is easy to understand, useful and/or actionable. Reduces the likelihood of misunderstandings or need for follow-up questions",
    "Compactness": "A response with high compactness is clear and to the point, without unnecessary elaboration",
}

# Initialize DynamoDB
dynamodb = boto3.resource("dynamodb")
login_table = dynamodb.Table("UserLogin")
chat_history_table = dynamodb.Table("ChatHistory")
evaluation_questions_table = dynamodb.Table("EvalQuestions")
evaluation_responses_table = dynamodb.Table("Evaluation")

app = FastAPI()


@app.get("/")
def read_main():
    return RedirectResponse(url=LOGIN_URL)


def get_access_token_and_user_info(url_code):
    global URL_CODE
    URL_CODE = url_code
    access_token_data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": URL_CODE,
        "redirect_uri": REDIRECT_URL,
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
            GET_ACCESS_TOKEN_URL, data=access_token_data, headers=access_token_headers
        )
        access_token = response.json()["access_token"]
        global ACCESS_TOKEN
        ACCESS_TOKEN = access_token

        # Get User Info
        response = requests.get(
            GET_USER_INFO_URL, headers=get_user_info_header(access_token)
        ).json()
        global USER_NAME
        global USERNAME
        global USER_EMAIL
        USER_NAME, USERNAME, USER_EMAIL = (
            response["name"],
            response["username"],
            response["email"],
        )

        # Log user login in DynamoDB
        log_user_login(USERNAME, ACCESS_TOKEN)

        return True
    except Exception as e:
        print(str(e))
        return False

def log_user_login(user_id, session_id):
        timestamp = time.time()
        dt = datetime.fromtimestamp(timestamp)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")
        login_data = {
            "Username": user_id,
            "SessionId": session_id,
            "Timestamp": timestamp,
        }
        login_table.put_item(Item=login_data)

# Sends a POST request to the MCM, Returns response
def get_mcm_response(question: str) -> str:
    response = httpx.post(
        MCM_URL,
        json={
            "question": question,
            "api_key": mcm_api_key.value,
            "Episodic_Knowledge": {},
        },
        timeout=timeout_secs.value,
    )
    return response.json()["response"]


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
        goto_eval_page_btn = gr.Button(
            value="Evaluate Ivy", link="/evaluation", scale=0.5
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

    def update_skill(skill_name):
        global MCM_SKILL
        global MCM_URL
        MCM_SKILL = skill_name
        MCM_URL = SKILL_NAME_TO_MCM_URL[skill_name]
        return []

    def on_askivy_page_load(skill_name, request: gr.Request):
        if not ACCESS_TOKEN:
            if "code" not in dict(request.query_params):
                # (TODO): Redirect to login page
                return "Go back to login page"
            url_code = dict(request.query_params)["code"]
            if not get_access_token_and_user_info(url_code):
                # (TODO): Redirect to Login page or display Error page
                return "An Error Occurred"

        if MCM_SKILL:
            skill_name = MCM_SKILL
        update_skill(skill_name)
        return [f"# Welcome to Ivy Chatbot, {USER_NAME}", skill_name]

    def log_chat_history(user_id, session_id, question, response, reaction):
        timestamp = time.time()
        dt = datetime.fromtimestamp(timestamp)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")

        chat_data = {
            "Username": user_id,
            "SessionId": session_id,
            "Timestamp": timestamp,
            "Question": question,
            "Response": response,
            "Reaction": reaction,
        }

        # Check if item exists and update or put item
        existing_item = chat_history_table.get_item(
            Key={
                "Username": user_id,
                "Timestamp": timestamp,
            }
        )

        if "Item" in existing_item:
            update_chat_history(user_id, session_id, question, response, reaction)
            print("Chat data updated successfully")
        else:
            chat_history_table.put_item(Item=chat_data)
            print("Chat data logged successfully")

    def update_chat_history(user_id, session_id, question, response, reaction):
        timestamp = time.time()
        dt = datetime.fromtimestamp(timestamp)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")

        # Update item in DynamoDB
        response = chat_history_table.update_item(
            Key={
                "Username": user_id,
                "Timestamp": timestamp,
            },
            UpdateExpression="SET Reaction = :reaction",
            ExpressionAttributeValues={":reaction": reaction},
            ReturnValues="UPDATED_NEW",
        )

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
            USERNAME, ACCESS_TOKEN, history[-1][0], history[-1][1], "no_reaction"
        )

    def log_commended_response(history):
        if len(history) == 0:
            return
        response = history[-1][1]
        question = history[-1][0]
        log_chat_history(USERNAME, ACCESS_TOKEN, question, response, "liked")
        gr.Info("Saved successfully!")

    def log_disliked_response(history):
        if len(history) == 0:
            return
        response = history[-1][1]
        question = history[-1][0]
        log_chat_history(USERNAME, ACCESS_TOKEN, question, response, "disliked")
        gr.Info("Saved successfully!")

    def log_flagged_response(history):
        if len(history) == 0:
            return
        response = history[-1][1]
        question = history[-1][0]
        log_chat_history(USERNAME, ACCESS_TOKEN, question, response, "flagged")
        gr.Info("Saved successfully!")

    def chat_liked_or_disliked(history, data: gr.LikeData):
        question = history[data.index[0]][0]
        response = history[data.index[0]][1]
        if data.liked:
            log_commended_response([[question, response]])
        else:
            log_disliked_response([[question, response]])

    def fetch_flagged_messages(user_id, session_id):
        response = chat_history_table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr("Username").eq(user_id)
            & boto3.dynamodb.conditions.Attr("SessionId").eq(session_id)
            & boto3.dynamodb.conditions.Attr("Reaction").eq("flagged")
        )
        return response.get("Items", [])

    def generate_csv(user_id, session_id):
        items = fetch_flagged_messages(user_id, session_id)
        if not items:
            return None

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M")
        temp_dir = tempfile.gettempdir()
        filepath = os.path.join(temp_dir, f"{user_id}_{timestamp}_flagged.csv")

        with open(filepath, mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "Username",
                    "Timestamp",
                    "Question",
                    "Response",
                    "Reaction",
                ]
            )
            for item in items:
                writer.writerow(
                    [
                        item["Username"],
                        item["Timestamp"],
                        item["Question"],
                        item["Response"],
                        item["Reaction"],
                    ]
                )

        return filepath

    def handle_download_click():
        filepath = generate_csv(USERNAME, ACCESS_TOKEN)
        return filepath if filepath else None

    ivy_main_page.load(on_askivy_page_load, [mcm_skill], [welcome_msg, mcm_skill])
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

evaluation_css = open("css/evaluation.css", "r").read()
with gr.Blocks(
    theme=gr.themes.Default(
        primary_hue=gr.themes.colors.teal, secondary_hue=gr.themes.colors.red
    ),
    css=evaluation_css,
) as evaluation_page:
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
        goto_askivy_page = gr.Button(value="Ask Ivy", link="/ask-ivy", scale=0.5)

    progress_bar = gr.HTML()

    with gr.Row():
        question_text = gr.Textbox(
            label="Evaluation Question",
            value="",
            interactive=False,
            scale=5,
        )
        submit_question_button = gr.Button(value="Submit", variant="primary")
        skip_question_button = gr.Button(value="Skip Question")
    response_text = gr.Textbox(
        label="Evaluation Response",
        placeholder="Response will appear here..",
        value="",
        interactive=False,
        scale=1,
        lines=5,
    )

    def get_metric_name(metric_name):
        return f"""
            <p>
                <div class="tooltip">{metric_name}
                <i class="fa fa-info-circle" style="font-size:10px;color:#007bff"></i>
                    <span class="tooltiptext" style="font-size:10px">{EVALUATION_METRIC_DESCRIPTION[metric_name]}</span>
                </div>
            </p>
        """

    metrics_evaluation_html = gr.HTML(
        f"""
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <div class='your-eval-container'>Enter your evaluations below</div> <br />
    <div class="eval-container">
        <table>
            <thead>
                <tr>
                    <th>Metrics</th>
                    <th>Strongly Disagree</th>
                    <th>Somewhat Disagree</th>
                    <th>Neutral</th>
                    <th>Somewhat Agree</th>
                    <th>Strongly Agree</th>
                </tr>
            </thead>
            <tbody>
                <tr style="background-color: #f9f9f9;">
                    <td>{get_metric_name("Correctness")}</td>
                    <td class="likert-label"><input type="radio" name="metric1" value="Strongly Disgree"></td>
                    <td class="likert-label"><input type="radio" name="metric1" value="Somewhat Disagree"></td>
                    <td class="likert-label"><input type="radio" name="metric1" value="Neutral"></td>
                    <td class="likert-label"><input type="radio" name="metric1" value="Somewhat Agree"></td>
                    <td class="likert-label"><input type="radio" name="metric1" value="Strongly Agree"></td>
                </tr>
                <tr style="background-color: #f0f0f0;">
                    <td>{get_metric_name("Completeness")}</td>
                    <td class="likert-label"><input type="radio" name="metric2" value="Strongly Disgree"></td>
                    <td class="likert-label"><input type="radio" name="metric2" value="Somewhat Disagree"></td>
                    <td class="likert-label"><input type="radio" name="metric2" value="Neutral"></td>
                    <td class="likert-label"><input type="radio" name="metric2" value="Somewhat Agree"></td>
                    <td class="likert-label"><input type="radio" name="metric2" value="Strongly Agree"></td>
                </tr>
                <tr style="background-color: #f9f9f9;">
                    <td>{get_metric_name("Confidence")}</td>
                    <td class="likert-label"><input type="radio" name="metric3" value="Strongly Disgree"></td>
                    <td class="likert-label"><input type="radio" name="metric3" value="Somewhat Disagree"></td>
                    <td class="likert-label"><input type="radio" name="metric3" value="Neutral"></td>
                    <td class="likert-label"><input type="radio" name="metric3" value="Somewhat Agree"></td>
                    <td class="likert-label"><input type="radio" name="metric3" value="Strongly Agree"></td>
                </tr>
                <tr style="background-color: #f0f0f0;">
                    <td>{get_metric_name("Comprehensibility")}</td>
                    <td class="likert-label"><input type="radio" name="metric4" value="Strongly Disgree"></td>
                    <td class="likert-label"><input type="radio" name="metric4" value="Somewhat Disagree"></td>
                    <td class="likert-label"><input type="radio" name="metric4" value="Neutral"></td>
                    <td class="likert-label"><input type="radio" name="metric4" value="Somewhat Agree"></td>
                    <td class="likert-label"><input type="radio" name="metric4" value="Strongly Agree"></td>
                </tr>
                <tr style="background-color: #f9f9f9;">
                    <td>{get_metric_name("Compactness")}</td>
                    <td class="likert-label"><input type="radio" name="metric5" value="Strongly Disgree"></td>
                    <td class="likert-label"><input type="radio" name="metric5" value="Somewhat Disagree"></td>
                    <td class="likert-label"><input type="radio" name="metric5" value="Neutral"></td>
                    <td class="likert-label"><input type="radio" name="metric5" value="Somewhat Agree"></td>
                    <td class="likert-label"><input type="radio" name="metric5" value="Strongly Agree"></td>
                </tr>
            </tbody>
        </table>
    </div><br />"""
    )

    with gr.Row():
        clear_button = gr.Button(value="Clear Rating", variant="stop")
        submit_rating_button = gr.Button(value="Next Question", variant="primary")

    def get_eval_dot_html(num, color_style):
        return f"""<div class="dot {color_style}">{num}</div>"""

    def create_progress_indicator(current_question):
        progress_html = """
        <div class="top-container">
            <div>
                <div class="progress-text">Evaluation Progress</div>
                <div class="dots">
                    %s
                </div>
            </div>
        </div>"""
        progress_dots_html = ""
        for i in range(len(EVALUATION_QUESTIONS)):
            if i < current_question:
                style = "green-dot"
            elif i > current_question:
                style = "red-dot"
            else:
                style = "yellow-dot"
            progress_dots_html += get_eval_dot_html(i + 1, style)
        progress_html = progress_html % progress_dots_html
        return progress_html

    submit_question_button.click(get_mcm_response, question_text, response_text)

    def get_submit_rating_btn():
        if EVALUATION_QUESTION_NUM == len(EVALUATION_QUESTIONS) - 1:
            return gr.Button(
                value="Submit and Finish Evaluation",
                variant="primary",
                link="/ask-ivy",
            )
        else:
            return submit_rating_button

    def get_skip_question_btn():
        if EVALUATION_QUESTION_NUM == len(EVALUATION_QUESTIONS) - 1:
            return gr.Button(value="Skip Question", interactive=False)
        else:
            return skip_question_button

    def skip_eval_question():
        global EVALUATION_QUESTIONS
        global EVALUATION_QUESTION_NUM
        EVALUATION_QUESTION_NUM += 1
        return [
            create_progress_indicator(EVALUATION_QUESTION_NUM),
            EVALUATION_QUESTIONS[EVALUATION_QUESTION_NUM][1],
            "",
            get_submit_rating_btn(),
            get_skip_question_btn(),
        ]

    skip_question_button.click(
        skip_eval_question,
        [],
        [
            progress_bar,
            question_text,
            response_text,
            submit_rating_button,
            skip_question_button,
        ],
    )

    clear_evaluation_rating_js = """
        function clear_selection() {
            selections = document.querySelectorAll('input[type="radio"]')
            selections.forEach(radio => {
                radio.checked = false;
            })
        }"""
    clear_button.click(
        None,
        inputs=[],
        outputs=[],
        js=clear_evaluation_rating_js,
    )

    def log_evaluation_response(response_text, eval_ratings):
        timestamp = time.time()
        dt = datetime.fromtimestamp(timestamp)
        timestamp = dt.strftime("%b-%d-%Y_%H:%M")
        global EVALUATION_QUESTIONS
        global EVALUATION_QUESTION_NUM
        eval_response_data = {
            "Timestamp": timestamp,
            "Username": USERNAME,
            "SessionId": ACCESS_TOKEN,
            "Skill": MCM_SKILL,
            "Question": EVALUATION_QUESTIONS[EVALUATION_QUESTION_NUM][1],
            "QuestionType": EVALUATION_QUESTIONS[EVALUATION_QUESTION_NUM][0],
            "Response": response_text,
            "Metric_Correctness": eval_ratings[0],
            "Metric_Completeness": eval_ratings[1],
            "Metric_Confidence": eval_ratings[2],
            "Metric_Comprehensibility": eval_ratings[3],
            "Metric_Compactness": eval_ratings[4],
        }
        evaluation_responses_table.put_item(Item=eval_response_data)

    def submit_rating_clear_update_question(response_concatenated_eval_ratings):
        response_text, concatenated_eval_ratings = (
            response_concatenated_eval_ratings.split("-")
        )
        log_evaluation_response(response_text, concatenated_eval_ratings.split(","))
        global EVALUATION_QUESTIONS
        global EVALUATION_QUESTION_NUM
        EVALUATION_QUESTION_NUM += 1
        return [
            create_progress_indicator(EVALUATION_QUESTION_NUM),
            EVALUATION_QUESTIONS[EVALUATION_QUESTION_NUM][1],
            "",
            get_submit_rating_btn(),
            get_skip_question_btn(),
        ]

    submit_rating_button_js = """
        function fetch_ratings_and_clear(response_text) {
            metric1_value = document.querySelector('input[name="metric1"]:checked')?.value || 'None';
            metric2_value = document.querySelector('input[name="metric2"]:checked')?.value || 'None';
            metric3_value = document.querySelector('input[name="metric3"]:checked')?.value || 'None';
            metric4_value = document.querySelector('input[name="metric4"]:checked')?.value || 'None';
            metric5_value = document.querySelector('input[name="metric5"]:checked')?.value || 'None';
            
            document.querySelectorAll('input[type="radio"]').forEach(radio => {
                radio.checked = false;
            });
            
            return response_text + '-' + [metric1_value, metric2_value, metric3_value, metric4_value, metric5_value].join();
        }
        """
    submit_rating_button.click(
        submit_rating_clear_update_question,
        inputs=[response_text],
        outputs=[
            progress_bar,
            question_text,
            response_text,
            submit_rating_button,
            skip_question_button,
        ],
        js=submit_rating_button_js,
    )

    def update_eval_questions(skill_name):
        response = evaluation_questions_table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr("Skill").eq(skill_name)
        )
        response = response.get("Items", [])
        global EVALUATION_QUESTIONS
        EVALUATION_QUESTIONS = []
        global EVALUATION_QUESTION_NUM
        EVALUATION_QUESTION_NUM = 0
        for question_dict in response:
            EVALUATION_QUESTIONS.append(
                (question_dict["QuestionType"], question_dict["Question"])
            )
        EVALUATION_QUESTIONS.sort()

    def update_skill(skill_name):
        global MCM_SKILL
        MCM_SKILL = skill_name
        global MCM_URL
        MCM_URL = SKILL_NAME_TO_MCM_URL[skill_name]
        update_eval_questions(skill_name)
        global EVALUATION_QUESTIONS
        global EVALUATION_QUESTION_NUM
        return [
            EVALUATION_QUESTIONS[EVALUATION_QUESTION_NUM][1],
            "",
            create_progress_indicator(EVALUATION_QUESTION_NUM),
        ]

    def on_eval_page_load(skill_name):
        print("EVAL page load")
        global MCM_SKILL
        print("MCM_SKILL", MCM_SKILL)
        if MCM_SKILL:
            skill_name = MCM_SKILL  # Maintain state across pages
        global EVALUATION_QUESTION_NUM
        first_question_to_display = update_skill(skill_name)[0]
        return [
            create_progress_indicator(EVALUATION_QUESTION_NUM),
            first_question_to_display,
            skill_name,
        ]

    evaluation_page.load(
        on_eval_page_load, [mcm_skill], [progress_bar, question_text, mcm_skill]
    )
    mcm_skill.change(
        update_skill, [mcm_skill], [question_text, response_text, progress_bar]
    )

app = gr.mount_gradio_app(app, ivy_main_page, path="/ask-ivy", root_path="/ask-ivy")
app = gr.mount_gradio_app(
    app, evaluation_page, path="/evaluation", root_path="/evaluation"
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)
