import json
import os
from dotenv import load_dotenv
import requests
import re
from datetime import datetime as dt, timedelta as td


from openai import OpenAI
import logging
import hashlib

load_dotenv()

from pymongo import MongoClient
from pymongo.server_api import ServerApi

#os.environ["OPENAI_API_KEY"] = "my-api-key" # <-- removed for security reasons (git commit)
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
client = OpenAI()

uri = "mongodb+srv://cluster0.tjii5rx.mongodb.net/?authSource=%24external&authMechanism=MONGODB-X509&retryWrites=true&w=majority&appName=Cluster0"
client = MongoClient(uri,
                     tls=True,
                     tlsCertificateKeyFile='/Users/arthur/www/personal/m-agent/X509-cert-4410348958562578187.pem',
                     server_api=ServerApi('1'))
jh_db = client['jobhelper01']
jobs = jh_db['jobs']
resumes = jh_db['resumes']
experience = jh_db['experience']
# print counts
print(jobs.count_documents({}))
print(resumes.count_documents({}))

def convert_time_interval_to_datetime(time_interval):
    # examples: "2 days ago", "2 hours ago"
    # extract the number and the unit
    if not time_interval:
        return None
    extracted = re.match(r"(\d+) (\w+)", time_interval)
    if not extracted:
        return None
    number, unit = extracted.groups()
    # create a timedelta from the number and the unit
    delta = td(**{unit: int(number)})
    # return the datetime object in utc without minute, second, or microsecond
    return dt.utcnow().replace(minute=0, second=0, microsecond=0) - delta


def save_job_listing(jobs_coll, job_result):
    '''
    Save a job listing to the database
    $jobs_coll: the collection to save the job listing to
    $job_result: the job listing to save
    '''
    # first check if job has been previously saved
    id = generate_hash(job_result['job_id'])[:16]
    existing_job = jobs_coll.find_one({"__id": id})
    if existing_job:
        # for now, always update the job listing
        return jobs_coll.update_one(
            {"__id": id}, 
            {"$set": {
                "listing": job_result, 
                "last_updated": dt.utcnow(),
                }
            }
        )
    else:
        detected_posted_at = job_result.get('detected_extensions', {}).get("posted_at")
        listing_created = convert_time_interval_to_datetime(detected_posted_at) or "unknown"
        full_job = {
            "__id": id,
            "listing": job_result,
            "created_at": listing_created,
            "first_seen": dt.utcnow(),
            "last_updated": dt.utcnow(),
        }
        return jobs_coll.insert_one(full_job)

def save_resume(resumes_coll, resume_title, resume_doc, title_keywords=None, google_doc_url=None):
    '''
    Save a resume to the database
    $resumes_coll: the collection to save the resume to
    $resume_title: the title of the resume
    $resume_doc: the resume document
    '''
    # first check if resume has been previously saved
    id_to_hash = google_doc_url or f"{resume_title} - {dt.utcnow().isoformat()}"
    id = generate_hash(id_to_hash)[:16]
    existing_resume = resumes_coll.find_one({"__id": id})
    if existing_resume:
        # for now, always update the resume
        return resumes_coll.update_one(
            {"__id": id}, 
            {"$set": {
                "title": resume_title,
                "resume_doc": resume_doc, 
                "title_keywords": title_keywords,
                "last_updated": dt.utcnow(),
                }
            }
        )
    else:
        full_resume = {
            "__id": id,
            "google_doc_url": google_doc_url,
            "created_at": dt.utcnow(),
            "title": resume_title,
            "resume_doc": resume_doc, 
            "title_keywords": title_keywords,
            "last_updated": dt.utcnow(),
        }
        return resumes_coll.insert_one(full_resume)
print("HI")
class ModelWrapper2(object):
    def __init__(self, client, model_type="open-ai-completion", system_message=None):
        self.client = client
        self.model_type = model_type
        self.system_message = system_message

    
    def response(self, prompt, context=None, system_message=None):
        print("HEY")
        if self.model_type == "open-ai-completion":
            system_message = self.system_message or "You are a technical assistant, skilled in answering questions in a friendly but succinct way."
            messages = [
                {"role": "system", "content": system_message},
            ]
            if context:
                messages.extend(context)
            messages.append({"role": "user", "content": prompt})
            print("HIIIII")
            completion = self.client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
            )
            # Todo: implement conv or user ID to allow conversation consistency
            return completion.choices[0].message.content

class CareerCoach(ModelWrapper2):
    def __init__(self, model_type="open-ai-completion"):
        command_agent_message = """
You are a career coach, but you are also very good at reading and writing JSON. 
In fact, when asked, you will only write JSON, without any formatting.
You are very helpful but also very honest! When trying to match a candidate to a job, you will try to infer experience
and skills from the resume and match them to the job description. If you can't find a match, you will say so.
"""
        print("HELLO")
        super().__init__(OpenAI(), model_type=model_type, system_message=command_agent_message)
    
    def generate_requirements_etc(self, job_blob, save=False):
        job_json = json.dumps(job_blob['listing'])
        prompt = """
Here is a job listing. Can you extract the following:
a full list of job requirements;
a full list of "soft" requirements or preferred qualifications;
a full list of job responsibilities;
the location (or locations) of the role
the in-office requirement (on-premises, remote, or hybrid; for hybrid, please include any specification of days/week in the office))
the salary range
Please use the body as well as any lists in the document. Please de-duplicate so no requirement or responsibility is listed twice.

Please output your answer JSON file, with the following structure: 
{"job_requirements":<list of requirements>, 
"preferred qualifications":<list_of_preferred qualifications>, 
"job_responsibilities":<list_of_responsibilities>,
"location": <list of locations, a singleton if only one is listed>,
"in_office_req": <in-office requirement: on-premises, remote, or hybrid (with specifications)>,
"salary_range": <salary range as a string>
}
Please just output the JSON, with no other words or formatting.

""" + job_json
        response = self.response(prompt, context=None)
        context = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response}
        ]
        prompt2 = """
Now, take the JSON output you generated above. We're going to create an instrument for evaluating candidates. 
First, for each requirement, qualification, and responsibility you generated, please estimate on a scale of 1-5 how *important* that item is for a candidate to have on their resume. You can use the tone of the description, the placement, and anything else to make your judgment. 
The output should be the same as the one you generated above, but with the following changes: for each requirement, qualification, and responsibility you evaluate, please replace that string (e.g., "Minimum 7 years experience managing a large factory" in the JSON blob with an object 
{
    "item": "Minimum 7 years experience managing a large factory", 
    "weight": <the importance score you gave to this item>, 
    "fit": "unknown", 
    "fit_reason": null
}
The "fit" and "fit_reason" attributes are for later use, when we evaluate the fit between this job description and a resume. 
"""
        response2 = self.response(prompt2, context=context)
        return response2

    def candidate_req_matrix(self, job_json, resume, save=False):
        print("CREATING MATRIX")
        prompt = """
I am going to provide you with two things:
1. A JSON blob representing a job listing, with requirements, qualifications, and responsibilities for an open position at a company.
2. A resume of a candidate, in markdown format. 

For each requirement, qualification, and responsibility in the job data provided, I want you to evaluate how well the candidate's resume matches that item. 
I also want you to provide a brief explanation of why you think the resume does or does not match the item, with a reference to the resume if possible.
The JSON blob will have the following structure:
{
    "job_requirements": [
        {"item": "Minimum 7 years experience managing a large factory", "weight": 5, "fit": "unknown", "fit_reason": null},
        {"item": "Bachelor's degree in mechanical engineering", "weight": 4, "fit": "unknown", "fit_reason": null},
        ...
    ],
    "preferred qualifications": [
        ...
    ],
    "job_responsibilities": [
        ...
    ],
    ...
}
For each item, I want you to replace the "fit" attribute with: 
"strong" if the resume matches the item well, 
"medium" if it seems to match it but not perfectly, 
"weak" if it does not match it at all, and
"not found" if you can't find the item in the resume.
For each item, I want you to replace the "fit_reason" attribute with a brief explanation of why you think the resume does or does not match the item, 
with a reference to the resume if possible.
The output should be a JSON blob with the same structure as the input, but with the "fit" and "fit_reason" attributes filled in.
Thank you!
""" + str(job_json) + str(resume)
        response = self.response(prompt, context=None)
        return response

    def match_candidate_to_job(self, matching_matrix, resume, save=False):
        """
        Given a matrix of job requirements and resume matches, evaluate the overall fit of the resume to the job.
        First
        """
        print("MATCHING")
        prompt = """
"""
model = ModelWrapper2(client=client)

class CommandAgent(ModelWrapper2):
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
    "api_key": SERPAPI_API_KEY,
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
        ret = requests.get(ret.json()["serpapi_pagination"]['next'], params={"api_key": SERPAPI_API_KEY})
        results = ret.json()['jobs_results']
        result_agg.extend(results)
    return result_agg


def generate_hash(input_string):
    # Use hashlib to create a hash object
    hash_object = hashlib.sha256(input_string.encode())  # You can choose a different hash algorithm
    # Return the hexadecimal representation of the hash
    return hash_object.hexdigest()



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

