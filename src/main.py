import os
import anthropic
import argparse
import yaml
import subprocess
from datetime import datetime
import uuid
from typing import Dict, Any, List, Optional, Union
import traceback
import sys
import logging
from logging.handlers import RotatingFileHandler


EDITOR_DIR = os.path.join(os.getcwd(), "data")
SESSIONS_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(SESSIONS_DIR, exist_ok=True)


# Fetch system prompts from environment variables or use defaults
BASH_SYSTEM_PROMPT = os.environ.get(
    "BASH_SYSTEM_PROMPT", "You are a helpful assistant that can execute bash commands."
)
EDITOR_SYSTEM_PROMPT = os.environ.get(
    "EDITOR_SYSTEM_PROMPT",
    "You are a helpful assistant that helps users edit text files.",
)


class SessionLogger:
    def __init__(self, session_id: str, sessions_dir: str):
        self.session_id = session_id
        self.sessions_dir = sessions_dir
        self.logger = self._setup_logging()

        # Initialize token counters
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def _setup_logging(self) -> logging.Logger:
        """Configure logging for the session"""
        log_formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(prefix)s - %(message)s"
        )
        log_file = os.path.join(self.sessions_dir, f"{self.session_id}.log")

        file_handler = RotatingFileHandler(
            log_file, maxBytes=1024 * 1024, backupCount=5
        )
        file_handler.setFormatter(log_formatter)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_formatter)

        logger = logging.getLogger(self.session_id)
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.setLevel(logging.DEBUG)

        return logger

    def update_token_usage(self, input_tokens: int, output_tokens: int):
        """Update the total token usage."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens

    def log_total_cost(self):
        """Calculate and log the total cost based on token usage."""
        cost_per_million_input_tokens = 3.0  # $3.00 per million input tokens
        cost_per_million_output_tokens = 15.0  # $15.00 per million output tokens

        total_input_cost = (
            self.total_input_tokens / 1_000_000
        ) * cost_per_million_input_tokens
        total_output_cost = (
            self.total_output_tokens / 1_000_000
        ) * cost_per_million_output_tokens
        total_cost = total_input_cost + total_output_cost

        prefix = "📊 session"
        self.logger.info(
            f"Total input tokens: {self.total_input_tokens}", extra={"prefix": prefix}
        )
        self.logger.info(
            f"Total output tokens: {self.total_output_tokens}", extra={"prefix": prefix}
        )
        self.logger.info(
            f"Total input cost: ${total_input_cost:.6f}", extra={"prefix": prefix}
        )
        self.logger.info(
            f"Total output cost: ${total_output_cost:.6f}", extra={"prefix": prefix}
        )
        self.logger.info(f"Total cost: ${total_cost:.6f}", extra={"prefix": prefix})


class EditorSession:
    def __init__(self, session_id: Optional[str] = None):
        """Initialize editor session with optional existing session ID"""
        self.session_id = session_id or self._create_session_id()
        self.sessions_dir = SESSIONS_DIR
        self.editor_dir = EDITOR_DIR
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.messages = []

        # Create editor directory if needed
        os.makedirs(self.editor_dir, exist_ok=True)

        # Initialize logger placeholder
        self.logger = None

        # Set log prefix
        self.log_prefix = "📝 file_editor"

    def set_logger(self, session_logger: SessionLogger):
        """Set the logger for the session and store the SessionLogger instance."""
        self.session_logger = session_logger
        self.logger = logging.LoggerAdapter(
            self.session_logger.logger, {"prefix": self.log_prefix}
        )

    def _create_session_id(self) -> str:
        """Create a new session ID"""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{timestamp}-{uuid.uuid4().hex[:6]}"

    def _get_editor_path(self, path: str) -> str:
        """Convert API path to local editor directory path"""
        # Strip any leading /repo/ from the path
        clean_path = path.replace("/repo/", "", 1)
        # Join with editor_dir
        full_path = os.path.join(self.editor_dir, clean_path)
        # Create the directory structure if it doesn't exist
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        return full_path

    def _handle_view(self, path: str, _: Dict[str, Any]) -> Dict[str, Any]:
        """Handle view command"""
        editor_path = self._get_editor_path(path)
        if os.path.exists(editor_path):
            with open(editor_path, "r") as f:
                return {"content": f.read()}
        return {"error": f"File {editor_path} does not exist"}

    def _handle_create(self, path: str, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """Handle create command"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(tool_call["file_text"])
        return {"content": f"File created at {path}"}

    def _handle_str_replace(
        self, path: str, tool_call: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Handle str_replace command"""
        with open(path, "r") as f:
            content = f.read()
        if tool_call["old_str"] not in content:
            return {"error": "old_str not found in file"}
        new_content = content.replace(
            tool_call["old_str"], tool_call.get("new_str", "")
        )
        with open(path, "w") as f:
            f.write(new_content)
        return {"content": "File updated successfully"}

    def _handle_insert(self, path: str, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """Handle insert command"""
        with open(path, "r") as f:
            lines = f.readlines()
        insert_line = tool_call["insert_line"]
        if insert_line > len(lines):
            return {"error": "insert_line beyond file length"}
        lines.insert(insert_line, tool_call["new_str"] + "\n")
        with open(path, "w") as f:
            f.writelines(lines)
        return {"content": "Content inserted successfully"}

    def log_to_session(self, data: Dict[str, Any], section: str) -> None:
        """Log data to session log file"""
        self.logger.info(f"{section}: {data}")

    def handle_text_editor_tool(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """Handle text editor tool calls"""
        try:
            command = tool_call["command"]
            if not all(key in tool_call for key in ["command", "path"]):
                return {"error": "Missing required fields"}

            # Get path and ensure directory exists
            path = self._get_editor_path(tool_call["path"])

            handlers = {
                "view": self._handle_view,
                "create": self._handle_create,
                "str_replace": self._handle_str_replace,
                "insert": self._handle_insert,
            }

            handler = handlers.get(command)
            if not handler:
                return {"error": f"Unknown command {command}"}

            return handler(path, tool_call)

        except Exception as e:
            self.logger.error(f"Error in handle_text_editor_tool: {str(e)}")
            return {"error": str(e)}

    def process_tool_calls(
        self, tool_calls: List[anthropic.types.ContentBlock]
    ) -> List[Dict[str, Any]]:
        """Process tool calls and return results"""
        results = []

        for tool_call in tool_calls:
            if tool_call.type == "tool_use" and tool_call.name == "str_replace_editor":

                # Log the keys and first 20 characters of the values of the tool_call
                for key, value in tool_call.input.items():
                    truncated_value = str(value)[:20] + (
                        "..." if len(str(value)) > 20 else ""
                    )
                    self.logger.info(
                        f"Tool call key: {key}, Value (truncated): {truncated_value}"
                    )

                result = self.handle_text_editor_tool(tool_call.input)
                # Convert result to match expected tool result format
                is_error = False

                if result.get("error"):
                    is_error = True
                    tool_result_content = [{"type": "text", "text": result["error"]}]
                else:
                    tool_result_content = [
                        {"type": "text", "text": result.get("content", "")}
                    ]

                results.append(
                    {
                        "tool_call_id": tool_call.id,
                        "output": {
                            "type": "tool_result",
                            "content": tool_result_content,
                            "tool_use_id": tool_call.id,
                            "is_error": is_error,
                        },
                    }
                )

        return results

    def process_edit(self, edit_prompt: str) -> List[Dict[str, Any]]:
        """Main method to process editing prompts"""
        try:
            # Initial message with proper content structure
            api_message = {
                "role": "user",
                "content": [{"type": "text", "text": edit_prompt}],
            }
            self.messages = [api_message]

            self.logger.info(f"User input: {api_message}")

            while True:
                response = self.client.beta.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=4096,
                    messages=self.messages,
                    tools=[
                        {"type": "text_editor_20241022", "name": "str_replace_editor"}
                    ],
                    system=EDITOR_SYSTEM_PROMPT,
                    betas=["computer-use-2024-10-22"],
                )

                # Extract token usage from the response
                input_tokens = getattr(response.usage, "input_tokens", 0)
                output_tokens = getattr(response.usage, "output_tokens", 0)
                self.logger.info(
                    f"API usage: input_tokens={input_tokens}, output_tokens={output_tokens}"
                )

                # Update token counts in SessionLogger
                self.session_logger.update_token_usage(input_tokens, output_tokens)

                self.logger.info(f"API response: {response.model_dump()}")

                # Convert response content to message params
                response_content = []
                for block in response.content:
                    if block.type == "text":
                        response_content.append({"type": "text", "text": block.text})
                    else:
                        response_content.append(block.model_dump())

                # Add assistant response to messages
                self.messages.append({"role": "assistant", "content": response_content})

                if response.stop_reason != "tool_use":
                    print(response.content[0].text)
                    break

                tool_results = self.process_tool_calls(response.content)

                # Add tool results as user message
                if tool_results:
                    self.messages.append(
                        {"role": "user", "content": [tool_results[0]["output"]]}
                    )

                    if tool_results[0]["output"]["is_error"]:
                        self.logger.error(
                            f"Error: {tool_results[0]['output']['content']}"
                        )
                        break

            # After the execution loop, log the total cost
            self.session_logger.log_total_cost()
            return self.messages

        except Exception as e:
            self.logger.error(f"Error in process_edit: {str(e)}")
            self.logger.error(traceback.format_exc())
            raise


class BashSession:
    def __init__(self, session_id: Optional[str] = None, no_agi: bool = False):
        """Initialize Bash session with optional existing session ID"""
        self.session_id = session_id or self._create_session_id()
        self.sessions_dir = SESSIONS_DIR
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.messages = []

        # Initialize a persistent environment dictionary for subprocesses
        self.environment = os.environ.copy()

        # Initialize logger placeholder
        self.logger = None

        # Set log prefix
        self.log_prefix = "🐚 bash"

        # Store the no_agi flag
        self.no_agi = no_agi

    def set_logger(self, session_logger: SessionLogger):
        """Set the logger for the session and store the SessionLogger instance."""
        self.session_logger = session_logger
        self.logger = logging.LoggerAdapter(
            session_logger.logger, {"prefix": self.log_prefix}
        )

    def _create_session_id(self) -> str:
        """Create a new session ID"""
        timestamp = datetime.now().strftime("%Y%m%d-%H:%M:%S-%f")
        # return f"{timestamp}-{uuid.uuid4().hex[:6]}"
        return f"{timestamp}"
    
    def _handle_datetime_tool(self) -> Dict[str, Any]:
        """Handle datetime tool execution using bash"""
        try:
            self.logger.info("Executing datetime tool via bash")
            result = self._handle_bash_command({"command": "date"})
            return result
            
        except Exception as e:
            self.logger.error(f"Error in _handle_datetime_tool: {str(e)}")
            self.logger.error(traceback.format_exc())
            return {"error": str(e)}

    def get_datetime(self) -> str:
        """Public method to get current datetime"""
        result = self._handle_datetime_tool()
        if "error" in result:
            self.logger.error(f"Error getting datetime: {result['error']}")
            return f"Error: {result['error']}"
        return result["content"]

    def _handle_bash_command(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """Handle bash command execution"""
        try:
            command = tool_call.get("command")
            restart = tool_call.get("restart", False)

            if restart:
                self.environment = os.environ.copy()  # Reset the environment
                self.logger.info("Bash session restarted.")
                return {"content": "Bash session restarted."}

            if not command:
                self.logger.error("No command provided to execute.")
                return {"error": "No command provided to execute."}

            # Check if no_agi is enabled
            if self.no_agi:
                self.logger.info(f"Mock executing bash command: {command}")
                return {"content": "in mock mode, command did not run"}

            # Log the command being executed
            self.logger.info(f"Executing bash command: {command}")

            # Execute the command in a subprocess
            result = subprocess.run(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.environment,
                text=True,
                executable="/bin/bash",
            )

            output = result.stdout.strip()
            error_output = result.stderr.strip()

            # Log the outputs
            if output:
                self.logger.info(
                    f"Command output:\n\n```output for '{command[:20]}...'\n{output}\n```"
                )
            if error_output:
                self.logger.error(
                    f"Command error output:\n\n```error for '{command}'\n{error_output}\n```"
                )

            if result.returncode != 0:
                error_message = error_output or "Command execution failed."
                return {"error": error_message}

            return {"content": output}

        except Exception as e:
            self.logger.error(f"Error in _handle_bash_command: {str(e)}")
            self.logger.error(traceback.format_exc())
            return {"error": str(e)}

    def process_tool_calls(
        self, tool_calls: List[anthropic.types.ContentBlock]
    ) -> List[Dict[str, Any]]:
        """Process tool calls and return results"""
        results = []

        for tool_call in tool_calls:
            if tool_call.type == "tool_use" and tool_call.name == "bash":
                self.logger.info(f"Bash tool call input: {tool_call.input}")

                result = self._handle_bash_command(tool_call.input)

                # Convert result to match expected tool result format
                is_error = False

                if result.get("error"):
                    is_error = True
                    tool_result_content = [{"type": "text", "text": result["error"]}]
                else:
                    tool_result_content = [
                        {"type": "text", "text": result.get("content", "")}
                    ]

                results.append(
                    {
                        "tool_call_id": tool_call.id,
                        "output": {
                            "type": "tool_result",
                            "content": tool_result_content,
                            "tool_use_id": tool_call.id,
                            "is_error": is_error,
                        },
                    }
                )

        return results

    def process_bash_command(self, bash_prompt: str) -> None:
        """Main method to process bash commands via the assistant"""
        try:
            # Initial message with proper content structure
            api_message = {
                "role": "user",
                "content": [{"type": "text", "text": bash_prompt}],
            }
            self.messages = [api_message]

            self.logger.info(f"User input: {api_message}")

            while True:
                response = self.client.beta.messages.create(
                    model="claude-3-5-sonnet-20241022",
                    max_tokens=4096,
                    messages=self.messages,
                    tools=[{"type": "bash_20241022", "name": "bash"}],
                    system=BASH_SYSTEM_PROMPT,
                    betas=["computer-use-2024-10-22"],
                )

                # Extract token usage from the response
                input_tokens = getattr(response.usage, "input_tokens", 0)
                output_tokens = getattr(response.usage, "output_tokens", 0)
                self.logger.info(
                    f"API usage: input_tokens={input_tokens}, output_tokens={output_tokens}"
                )

                # Update token counts in SessionLogger
                self.session_logger.update_token_usage(input_tokens, output_tokens)

                self.logger.info(f"API response: {response.model_dump()}")

                # Convert response content to message params
                response_content = []
                for block in response.content:
                    if block.type == "text":
                        response_content.append({"type": "text", "text": block.text})
                    else:
                        response_content.append(block.model_dump())

                # Add assistant response to messages
                self.messages.append({"role": "assistant", "content": response_content})

                if response.stop_reason != "tool_use":
                    # Print the assistant's final response
                    print(response.content[0].text)
                    break

                tool_results = self.process_tool_calls(response.content)

                # Add tool results as user message
                if tool_results:
                    self.messages.append(
                        {"role": "user", "content": [tool_results[0]["output"]]}
                    )

                    if tool_results[0]["output"]["is_error"]:
                        self.logger.error(
                            f"Error: {tool_results[0]['output']['content']}"
                        )
                        break

            # After the execution loop, log the total cost
            self.session_logger.log_total_cost()

        except Exception as e:
            self.logger.error(f"Error in process_bash_command: {str(e)}")
            self.logger.error(traceback.format_exc())
            raise


# def main():
#     """Main entry point"""
#     parser = argparse.ArgumentParser()
#     parser.add_argument("prompt", help="The prompt for Claude", nargs="?")
#     parser.add_argument(
#         "--mode", choices=["editor", "bash"], default="editor", help="Mode to run"
#     )
#     parser.add_argument(
#         "--no-agi",
#         action="store_true",
#         help="When set, commands will not be executed, but will return 'command ran'.",
#     )
#     args = parser.parse_args()

#     # Create a shared session ID
#     session_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
#     # Create a single SessionLogger instance
#     session_logger = SessionLogger(session_id, SESSIONS_DIR)

#     if args.mode == "editor":
#         session = EditorSession(session_id=session_id)
#         # Pass the logger via setter method
#         session.set_logger(session_logger)
#         print(f"Session ID: {session.session_id}")
#         session.process_edit(args.prompt)
#     elif args.mode == "bash":
#         session = BashSession(session_id=session_id, no_agi=args.no_agi)
#         # Pass the logger via setter method
#         session.set_logger(session_logger)
#         print(f"Session ID: {session.session_id}")
#         session.process_bash_command(args.prompt)

if __name__ == "__main__":
    # main()
    print("Hello from Agent Athreya!")
