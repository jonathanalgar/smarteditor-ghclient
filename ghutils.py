import asyncio
import logging
import os
import subprocess

from github import Github


class GitHubHandler:
    """
    Manages interactions with GitHub using PyGithub, focusing on pull request operations.

    Attributes:
        github_obj (Github): PyGithub instance for GitHub API interactions.
        repo (Repository): GitHub repository associated with the pull request.
        pr (PullRequest): Pull request object for commenting or reviewing.
    """
    def __init__(self, repo_name, pr_number):
        """
        Initializes GitHubHandler with repository and pull request details.

        Args:
            repo_name (str): Repository name.
            pr_number (int): Pull request number.
        """
        self.github_obj = Github(os.getenv('GITHUB_TOKEN'))
        self.repo = self.github_obj.get_repo(repo_name)
        self.pr = self.repo.get_pull(pr_number)

    def post_comment(self, message):
        """
        Posts a comment to the pull request.

        Args:
            message (str): Comment content.
        """
        self.pr.create_issue_comment(message)

    def add_reaction_to_comment(self, comment_id, reaction_type):
        """
        Adds a reaction to a pull request comment.

        Args:
            comment_id (int): The ID of the comment.
            reaction_type (str): The type of reaction to add.
        """
        try:
            comment = self.github_obj.get_repo(self.repo.full_name).get_issue(self.pr.number).get_comment(comment_id)
            comment.create_reaction(reaction_type)
        except Exception as e:
            logging.error(f'Failed to add reaction to comment {comment_id}: {str(e)}')

    def commit_and_push(self, updated_files, commit_message):
        """
        Commits and pushes specified files to the git repository.

        Args:
            updated_files (list of str): File paths to commit.
            commit_message (str): Commit message.

        Returns:
            bool: True if successful, False otherwise.
        """
        file_paths_str = "[" + ", ".join(updated_files) + "]"
        logging.info(f"{file_paths_str} Initiating commit and push process")

        try:
            current_directory = os.getcwd()
            subprocess.run(['git', 'config', '--global', '--add', 'safe.directory', current_directory], check=True)
            subprocess.run(['git', 'config', 'user.name', 'github-actions'], check=True)
            subprocess.run(['git', 'config', 'user.email', 'github-actions@github.com'], check=True)

            if subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True).stdout:
                subprocess.run(['git', 'add'] + updated_files, check=True)
                commit_result = subprocess.run(['git', 'commit', '-m', commit_message], capture_output=True, text=True)

                if commit_result.returncode == 0:
                    logging.info(f"{file_paths_str} Changes committed successfully")
                    push_result = subprocess.run(['git', 'push'], capture_output=True, text=True)
                    if push_result.returncode == 0:
                        logging.info(f"{file_paths_str} Changes pushed to remote repository successfully.")
                        return True
                    else:
                        logging.error(f"{file_paths_str} Failed to push changes")
                        return False
                else:
                    logging.error(f"{file_paths_str} Failed to commit changes")
                    return False
            else:
                logging.info(f"{file_paths_str} No changes to commit")
                return False
        except subprocess.CalledProcessError as e:
            logging.error(f"{file_paths_str} Error during git operations: {e}")
            return False

    def get_file_status(self, file_path):
        """
        Retrieves the status of a file in the context of the pull request.

        The method checks the list of files in the pull request and returns the status
        of the specified file. The status can indicate whether the file is added, modified, or deleted.

        Args:
            file_path (str): The relative path of the file in the repository for which the status is required.
        """
        pr_files = self.pr.get_files()
        return next(
            (file.status for file in pr_files if file.filename == file_path), None
        )
