from crewai_tools import BaseTool
from serpapi import GoogleSearch


class JobSearchTool(BaseTool):
    name: str = "Job Search tool"
    description: str = (
        "A tool for finding jobs. The argument should be the job title, location (if any), and recency info (for example: today, this week, last 3 days)."
    )

    def _run(self, argument: str) -> str:
        print(f"Running my job search tool with argument: {argument}")
        # Implementation goes here

        params = {
        "api_key": "2ed07e54e8562266a5df0cd206c1a66ea708775e3e3c22ae96e8cac1613f2823",
        "engine": "google_jobs",
        "google_domain": "google.com",
        "q": argument
        }

        search = GoogleSearch(params)
        results = search.get_dict()
        return "Here are some job results: " + str(results)
