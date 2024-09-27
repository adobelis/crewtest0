import json
import os
import requests

from openai import OpenAI
import logging

#os.environ["OPENAI_API_KEY"] = "my-api-key" # <-- removed for security reasons (git commit)
client = OpenAI()


class ModelWrapper(object):
    def __init__(self, client, model_type="open-ai-completion", system_message=None):
        self.client = client
        self.model_type = model_type
        self.system_message = system_message

    
    def response(self, prompt, context=None, system_message=None):
        if self.model_type == "open-ai-completion":
            system_message = self.system_message or "You are a technical assistant, skilled in answering questions in a friendly but succinct way."
            messages = [
                {"role": "system", "content": system_message},
            ]
            if context:
                def switch_keys(el):
                    return dict(role=el["sender"], content=el["text"])
                context = [switch_keys(a) for a in context]
                messages.extend(context)
            messages.append({"role": "user", "content": prompt})
            completion = self.client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
            )
            # Todo: implement conv or user ID to allow conversation consistency
            return completion.choices[0].message.content

model = ModelWrapper(client=client)

class CommandAgent(ModelWrapper):
    def __init__(self, client, model_type="open-ai-completion"):
        command_agent_message = """
You are an AI Agent, and I am going to ask you to do things and output unformatted JSON that represents the action I want you to take. 
The correct response for each request is in the form {action: <action>, inputs: <inputs>}.
The valid values for <action> are "web search", "navigate to", and "save". 
The valid input value for the action "web search" is two strings, which you should put into JSON format: {"query": <the query string for the search>, "domain":<the domain, if you can infer one of the following valid domains: jobs, news -- otherwise the domain is "search">}.
The valid input value for the action "navigate to" is a string, the target URL. 
The valid input value for the action "save" is two strings, which you should put into JSON format: {"key": <location to save the string>, "value": <the string to be saved>}. 
The valid input value for the action "retrieve" is a string, the key or location (such as a file name) where a piece of information is stored. The idea here is we are retrieving a value from a data store. You are just simplifying the command so it can be passed to code.
"""
        super().__init__(client, model_type=model_type, system_message=command_agent_message)
    
    def action(self, prompt, context=None):
        return self.response(prompt, context=context)

class UserData(object):
    def __init__(self, user_country=None, user_language=None, user_location=None):
        self.user_language = user_language or "en"
        self.user_country = user_country or "us"
        self.user_location = user_location or "New York, New York, United States"


def job_search_tool(argument, user_data=None, result_count=10):
    user_data = user_data or UserData()
    hl = user_data.user_language or "en"
    gl = user_data.user_country or "us"
    location = user_data.user_location or "New York, New York, United States"
    params = {
    "api_key": "2ed07e54e8562266a5df0cd206c1a66ea708775e3e3c22ae96e8cac1613f2823",
    "engine": "google_jobs",
    "google_domain": "google.com",
    "q": "Product Manager",
    "hl": hl,
    "gl": gl,
    "location": location,
    }
    print(params)
    ret = requests.get("https://serpapi.com/search", params=params)
    # if ret.status_code != 200:
    #     return f"Error: {ret.status_code}"
    results = ret.json()['jobs_results']

    result_agg = results
    while len(result_agg) < result_count and ret.json().get("serpapi_pagination", {}).get('next'):
        print(f"{len(result_agg)} {len(results)}")
        ret = requests.get(ret.json()["serpapi_pagination"]['next'], params={"api_key":"2ed07e54e8562266a5df0cd206c1a66ea708775e3e3c22ae96e8cac1613f2823"})
        results = ret.json()['jobs_results']
        result_agg.extend(results)
    return result_agg


def binary_class(model, qualifier, prompt):
    llm_prompt = f"yes or no: is the following text {qualifier}? {prompt}"
    # print(f"LLM prompt: {llm_prompt}")
    logging.info(f"LLM prompt: {llm_prompt}")
    answer = model.response(llm_prompt)
    # print(f"Answer {answer}") 
    logging.info(f"Answer {answer}")
    if "yes" in answer.lower(): 
        return True
    elif "no" in answer.lower():
        return False
    else: 
        raise(Exception(f"Unexpected answer from binary classifier: {answer}"))

def list_to_nl_list(word_list):
    if not word_list:
        raise(Exception("word list is null or zero length"))
    if len(word_list) == 1:
        return word_list[0]
    elif len(word_list) > 1:
        return ", ".join(word_list[0:-1]) + " and {}".format(word_list[-1])
    

def extract_data(model, target_list, prompt, domain=None, substitution=None):
    """
    Extract one or more substrings from a block of text. Example: 
    'Extract a starting location, a destination, and a mode of transportation 
    in the context of transit directions,
    from the following text: "I'd like to to go
    from Hotel Foch to the Eiffel Tower"'
    Response (dict): {"starting location": "Hotel Foch", "destination": "Eiffel Tower", "mode of transportation": None}
    """
    
    domain = f"in the context of {domain}" if domain else ""

    nl_list = list_to_nl_list(target_list)
    nl_list_keys = list_to_nl_list([f'"{a}"' for a in target_list])
    # print(f"NL list: {nl_list}, {nl_list_keys}")
    # print(f"Substitutions: {substitution}")
    logging.info(f"NL list: {nl_list}, {nl_list_keys}")
    logging.info(f"Substitutions: {substitution}")
    im_prompt = " ".join([
        "Please follow the following technical instructions.", 
        "Please output the answer, don't give me some code to do it.",
        f"Extract the {nl_list} from the following text,"
        f"and output them in a JSON map with keys {nl_list_keys}.",
        "If no text can be identified for any of the above categories, the value of the map for that key should be null.",
        "" if substitution is None else substitution,
        f'Here is the text: "{prompt}".'
    ])
    # print(f"\nim_prompt {im_prompt}\n")
    logging.info(f"\nim_prompt {im_prompt}\n")
    completion = model.client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a technical assistant, skilled in answering questions in a friendly but succinct way."},
            {"role": "user", "content": im_prompt}
        ]
    )
    completion_content = completion.choices[0].message.content
    # print(f"completion_content: {completion_content}")
    logging.info(f"completion_content: {completion_content}")
    extracted_data = json.loads(completion_content)
    return extracted_data


def get_google_directions(inputs):
    """
    Stub for now
    """
    return "Drive three miles down Avenue Foch; your destination will be on the right."

def augment_from_data_source(user_prompt, context=None, model=None, user_location=None):
    if not model:
        model = ModelWrapper(client=client)
    if binary_class(model, "a question about a directions or traffic", user_prompt):
        if binary_class(model, "a question about directions, " +
            "which can include something as simple as \"directions to [place name]\""+
            " or \"how do I get to [place name]\"", 
            user_prompt):
            return get_directions_data(user_prompt, context=context, model=model, user_location=user_location)
        elif binary_class(model, "a question about traffic", user_prompt):
            return get_directions_data(user_prompt, context=context, model=model, user_location=user_location)
        else:
            return "Good question! Right now, I can only give directions from here to there, but I'm learning more every day.", None
    else:
        return model.response(user_prompt, context=context), None
    
def get_directions_data(user_prompt, context=None, model=None, user_location=None):
    ev = [
        "a starting location", 
        "a destination", 
        "a mode of transportation"
    ]
    substitution = 'If the value of one of the categories is implied to be the user\'s location, the value for that key should be "here".'
    directions_inputs = extract_data(model, 
                                        target_list=ev, 
                                        prompt=user_prompt, 
                                        domain="asking directions",
                                        substitution=substitution)
    origin = directions_inputs[ev[0]]
    destination = directions_inputs[ev[1]]
    mode = directions_inputs[ev[2]]
    if origin == "here":
        origin = user_location
    if destination == "here":
        destination = user_location
    if origin == "here" or destination == "here" and not user_location:
        return "I'm sorry, it looks like you want directions from your current location, but I don't have that information. Please provide both origin and destination."
    if not origin or not destination:
        return "I'm sorry, I couldn't find both an origin and a destination in your text. Please provide both.", None
    mode = mode or "driving"
    # print(f"Origin: {origin}, Destination: {destination}, Mode: {mode}")
    logging.info(f"Origin: {origin}, Destination: {destination}, Mode: {mode}")
    directions = gmap.get_directions(origin, destination, mode)
    # print(f"Directions: {directions}")
    logging.info(f"Directions: {directions}")
    tt_info =  f"Travel time right now: {directions.get('duration_in_traffic')}, usual travel time: {directions['duration']}; distance: {directions['distance']}" \
        if directions.get("duration_in_traffic") else ""
    re_prompt = "\n".join([
        "Please answer the following question about directions (or traffic) using your own knowledge and the following information:",
        f'User\'s location: {user_location}; refer to this as "your current location" -- don\'t mention the coordinates.' if user_location else "",
        f"Question: {user_prompt}",
        f"Directions information from {origin} to {destination} via {mode}:",
        f"{tt_info}"
        f"Steps {directions['steps']}"
    ])
    directions.update({"origin": origin, "destination": destination, "mode": mode})
    return model.response(re_prompt, context=context), directions

