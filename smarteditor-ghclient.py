import asyncio
import logging
import os
import re

import aiohttp

from ghutils import GitHubHandler

logging.basicConfig(level=logging.DEBUG,
                    format='%(levelname)s [%(asctime)s] %(message)s',
                    datefmt='%d-%m-%Y %H:%M:%S')


class SmartEditorHandler:
    """
    Handles retrieval and updating of suggestions.
    """
    def __init__(self):
        pass

    async def send_to_smarteditor(self, session, file_path, text, smarteditor_endpoint):
        """
        Asynchronously sends text content to SMARTEDITOR_ENDPOINT and retrieves suggestions.

        Args:
            session (ClientSession): An aiohttp client session for making HTTP requests.
            text (str): The text to be sent for review.
            smarteditor_endpoint (str): Smarteditor service URL.

        Returns:
            dict: A dictionary containing the response from SMARTEDITOR_ENDPOINT.
        """
        SMARTEDITOR_TIMEOUT = 120
        response_structure = {"success": False, "data": None}

        logging.info(f'[{file_path}] Sending request to SMARTEDITOR_ENDPOINT')
        headers = {
            "Content-Type": "application/json",
            "X-API-Token": os.getenv('SMARTEDITOR_TOKEN')
        }
        payload = {"text": text}
        try:
            async with session.post(smarteditor_endpoint, json=payload, headers=headers, timeout=SMARTEDITOR_TIMEOUT) as response:
                response.raise_for_status()
                response_structure["data"] = await response.json()
                response_structure["success"] = True
        except asyncio.TimeoutError:
            logging.error(f'[{file_path}] Request to SMARTEDITOR_ENDPOINT timed out')
        except aiohttp.ClientResponseError as e:
            logging.error(f'[{file_path}] HTTP Response Error: {e}')
        except Exception as e:
            logging.error(f'[{file_path}] An unexpected error occurred: {e}')

        return response_structure

    def format_smarteditor_suggestions(self, violations):
        """
        Formats the response from SMARTEDITOR_ENDPOINT.

        Takes a list of violation objects and formats them into a string that lists the original sentences and their suggested revisions along with explanations.

        Args:
            violations (list): A list of violation objects returned by SMARTEDITOR_ENDPOINT.

        Returns:
            str: A formatted string representing the smarteditor suggestions.
        """
        formatted_suggestions = [
            f"**Original:** {violation['original_sentence']}\n**Revised:** {violation['revised_sentence']}\n**Explanation:** {violation['clear_explanation']}\n\n"
            for violation in violations
        ]
        return '\n'.join(formatted_suggestions)

    def post_review_comment_on_violation(self, file_path, violation, github_handler, pr_number):
        """
        Posts a review comment on a specific line of a file in a pull request, highlighting an instance of passive voice.

        Args:
            file_path (str): The path of the file within the pull request.
            violation (dict): A dictionary containing details about the violation, including original and suggested text.
            github_handler (GitHubHandler): An instance of GitHubHandler for GitHub interaction.
            pr_number (int): The number of the pull request.
        """
        pr = github_handler.repo.get_pull(pr_number)
        commit_obj = github_handler.repo.get_commit(pr.head.sha)

        files = pr.get_files()
        for file in files:
            if file.filename == file_path:
                file_diff = file.patch
                break
        else:
            logging.warning(f"[{file_path}] File not found in pull request")
            return

        # Locating the exact line in the file diff where the original passive sentence appears.
        diff_lines = file_diff.split('\n')
        for i, line in enumerate(diff_lines):
            if violation['original_sentence'] in line:
                position = i
                line_text = line[line.find('+')+1:]  # Skip the diff '+'
                updated_line = line_text.replace(violation['original_sentence'], violation['revised_sentence'])

                review_message = f"**Suggested Change:**\n```suggestion\n{updated_line}\n```\n"
                review_message += f"**Explanation:** {violation['clear_explanation']}"
                pr.create_review_comment(review_message, commit_obj, file_path, position)
                logging.info(f"[{file_path}] Posted a review comment for instance of passive voice on line {position}")


def parse_smarteditor_comment(file_path, comment_body):
    """
    Parses the body of the smarteditor comment and extracts original and revised sentences.

    Args:
        comment_body (str): The body of the smarteditor comment.

    Returns:
        List[Tuple[str, str]]: A list of tuples, each containing the original and revised sentences extracted from the comment.
    """
    logging.debug(f"[{file_path}] Parsing smarteditor command comment: {comment_body}")

    pattern = re.compile(r"\*\*Original:\*\*\s(.*?)\n\*\*Revised:\*\*\s(.*?)\n\*\*Explanation:\*\*", re.DOTALL)
    matches = pattern.findall(comment_body)

    if not matches:
        logging.warning(f"[{file_path}] No matches found in smarteditor comment. Review regex pattern and comment format")
    else:
        logging.info(f"[{file_path}] Extracted tuples from smarteditor comment: {matches}")

    return matches


async def commit_edited_file(github_handler, file_path, pr_number):
    """
    Commits the edited file to the repository based on the complete suggestions from the last smarteditor review comment.

    Args:
        github_handler (GitHubHandler): An instance of GitHubHandler for interacting with GitHub.
        file_path (str): The path of the file to be edited.
        pr_number (int): The number of the pull request associated with the file.
    """
    pr = github_handler.repo.get_pull(pr_number)
    comments = pr.get_issue_comments()

    # Convert PaginatedList to a list and reverse it to start from the latest comment
    pr_comments = list(comments)
    pr_comments.reverse()

    latest_review_comment = next(
        (
            comment
            for comment in pr_comments
            if f"SMARTEDITOR suggestions for `{file_path}`" in comment.body
        ),
        None,
    )
    if not latest_review_comment:
        logging.error(f"[{file_path}] Failed to find smarteditor review comment. Unable to proceed with commit")
        return

    suggestions = parse_smarteditor_comment(file_path, latest_review_comment.body)
    logging.info(f"[{file_path}] Extracted tuples from smarteditor comment: {suggestions}")
    with open(file_path, 'r') as file:
        content = file.read()

    replacements_made = 0
    for original, revised in suggestions:
        if original in content:
            content = content.replace(original, revised)
            replacements_made += 1
            logging.info(f"[{file_path}] Replaced: '{original}' with '{revised}'")
        else:
            logging.warning(f"[{file_path}] Original sentence not found in file: '{original}'")

    logging.info(f"[{file_path}] Total text replacements made in file: {replacements_made}")

    if replacements_made > 0:
        with open(file_path, 'w') as file:
            file.write(content)

        github_handler.commit_and_push([file_path], f"Posted a commit comment for file: {file_path}")
    else:
        logging.info(f"[{file_path}] No text replacements required. Skipping the commit process")


async def process_file(session, file_path, smarteditor_handler, github_handler, smarteditor_endpoint, pr_number):
    """
    Processes a file to make suggestions on instances of passive voice.

    Args:
        session (aiohttp.ClientSession): The client session for HTTP requests.
        file_path (str): The path of the file to be processed.
        smarteditor_handler (SMARTEDITORHandler): An instance of SMARTEDITORHandler for processing.
        github_handler (GitHubHandler): An instance of GitHubHandler for interacting with GitHub.
        smarteditor_endpoint (str): SMARTEDITOR service URL.
        pr_number (int): The number of the associated pull request.
    """
    logging.info(f"[{file_path}] Starting review")

    try:
        with open(file_path, 'r') as file:
            content = file.read()

        response = await smarteditor_handler.send_to_smarteditor(session, file_path, content, smarteditor_endpoint)

        if not response["success"]:
            logging.error(f"[{file_path}] Failed to get a response from SMARTEDITOR_ENDPOINT.")
            github_handler.post_comment(f"Failed to get a response from the SMARTEDITOR_ENDPOINT for file `{file_path}`. Please check the logs for more details.")
            return

        if not response["data"].get('violations'):
            logging.info(f"[{file_path}] No instances of sentences written in passive voice found")
            github_handler.post_comment(f"There appear to be no instances of sentences that violate the style guide rules in `{file_path}`.")
            return

        file_status = github_handler.get_file_status(file_path)
        run_url = response["data"].get('run_url')
        run_url_text = f"[Explore how the LLM generated them.]({run_url})" if run_url else ""

        if file_status == 'added':
            review_comment = f"SMARTEDITOR suggestions for `{file_path}` posted below."
            if run_url:
                review_comment += f" {run_url_text}"
            github_handler.post_comment(review_comment)

            for violation in response["data"]['violations']:
                smarteditor_handler.post_review_comment_on_violation(file_path, violation, github_handler, pr_number)

        elif file_status == 'modified':
            formatted_response = smarteditor_handler.format_smarteditor_suggestions(response["data"]['violations'])
            final_comment = f"SMARTEDITOR suggestions for `{file_path}`:\n\n{formatted_response}"
            if run_url:
                final_comment += run_url_text

            final_comment += f" Use `/smarteditor {file_path} --commit` to commit all suggestions."
            github_handler.post_comment(final_comment)

    except Exception as e:
        logging.error(f"[{file_path}] Error processing file: {e}")
        github_handler.post_comment(f"Error processing file `{file_path}`. Please check the logs for more details.")


async def main():
    """
    Main asynchronous function to run the script.
    """
    repo_name = os.getenv('GITHUB_REPOSITORY')
    pr_number = os.getenv('PR_NUMBER')
    comment_id = os.getenv('COMMENT_ID')
    comment_body = os.getenv('COMMENT_BODY', '')
    smarteditor_endpoint = os.getenv('SMARTEDITOR_ENDPOINT')

    pr_number = int(pr_number) if pr_number else None
    comment_id = int(comment_id) if comment_id else None

    logging.debug(f"Received comment body (raw): {repr(comment_body)}")

    github_handler = GitHubHandler(repo_name, pr_number)
    smarteditor_handler = SmartEditorHandler()

    SUPPORTED_FILE_TYPES = ['.md', '.mdx', '.ipynb']
    file_types_regex = r"(" + '|'.join(re.escape(ext) for ext in SUPPORTED_FILE_TYPES) + r")"

    if commit_match := re.search(
        rf'/smarteditor\s+([\w/.\-]*[\w.\-]+{file_types_regex})\s+--commit', comment_body
    ):
        file_path = commit_match[1]
        logging.info(f"[{file_path}] Commit command identified")

        await commit_edited_file(github_handler, file_path, pr_number)
    elif file_path_match := re.search(
        rf'/smarteditor\s+([\w/.\-]*[\w.\-]+{file_types_regex})', comment_body
    ):
        file_path = file_path_match[1]
        logging.info(f"[{file_path}] File path identified")

        async with aiohttp.ClientSession() as session:
            await process_file(session, file_path, smarteditor_handler, github_handler, smarteditor_endpoint, pr_number)
    else:
        logging.info("No valid command found in the comment.")

        supported_types_formatted = ", ".join(f"`{ext}`" for ext in SUPPORTED_FILE_TYPES)
        github_handler.post_comment(f"No valid command found in the comment. Supported file types are: {supported_types_formatted}")

if __name__ == "__main__":
    asyncio.run(main())
