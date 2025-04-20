import discord
from redbot.core import commands
import subprocess
import tempfile
import os
import re
from typing import Optional

class CodeValidator(commands.Cog):
    """Validates code syntax for various programming languages."""

    def __init__(self, bot):
        self.bot = bot
        self.language_extensions = {
            "py": "python",
            "js": "javascript",
            "java": "java",
            "c": "c",
            "cpp": "c++",
            "cs": "c#",
            "go": "go",
            "rb": "ruby",
            "php": "php",
            "rs": "rust",
            "sh": "bash",
            "html": "html",
            "css": "css",
            "ts": "typescript",
            "swift": "swift",
            "kt": "kotlin",
            "sql": "sql"
        }
        self.language_validators = {
            "python": self._validate_python,
            "javascript": self._validate_javascript,
            "typescript": self._validate_typescript,
            "java": self._validate_java,
            "c": self._validate_c,
            "c++": self._validate_cpp,
            "c#": self._validate_csharp,
            "go": self._validate_go,
            "ruby": self._validate_ruby,
            "php": self._validate_php,
            "rust": self._validate_rust,
            "bash": self._validate_bash,
            "html": self._validate_html,
            "css": self._validate_css,
            "swift": self._validate_swift,
            "kotlin": self._validate_kotlin,
            "sql": self._validate_sql
        }

    @commands.command()
    async def validate(self, ctx, *, code: str = None):
        """
        Validates code syntax.
        
        Usage: [p]validate ```language
        code here
        ```
        The language can be auto-detected from code blocks.
        """
        if not code:
            await ctx.send("Please provide code to validate. Use: `[p]validate ```language\ncode here\n```")
            return

        # Extract code from code blocks if present
        code_block_pattern = r"```(\w*)\n([\s\S]+?)\n```"
        match = re.search(code_block_pattern, code)
        
        language = None
        if match:
            lang_hint = match.group(1).lower()
            code = match.group(2)
            if lang_hint:
                for ext, lang in self.language_extensions.items():
                    if lang_hint == ext or lang_hint == lang:
                        language = lang
                        break
        
        # If we didn't get the language from a code block, try to detect it
        if not language:
            language = self._detect_language(code)
        
        if not language:
            await ctx.send("Couldn't detect the programming language. Please specify using ```language\ncode\n```")
            return
        
        # Send initial response
        response = await ctx.send(f"Validating {language} code...")
        
        # Validate the code
        if language in self.language_validators:
            result = await self.language_validators[language](code)
            if result["valid"]:
                await response.edit(content=f"✅ **Validated!** Your {language} code has no syntax errors.")
            else:
                error_msg = f"❌ **Error in {language} code:**\n```\n{result['error']}\n```"
                await response.edit(content=error_msg)
        else:
            await response.edit(content=f"Sorry, validation for {language} is not supported yet.")

    def _detect_language(self, code: str) -> Optional[str]:
        """Try to detect the programming language based on code patterns."""
        # Simple heuristic-based detection
        if "import " in code or "def " in code or "class " in code and ":" in code:
            return "python"
        elif "function" in code or "var " in code or "let " in code or "const " in code:
            if "interface " in code or "type " in code or "<" in code and ">" in code:
                return "typescript"
            return "javascript"
        elif "public class" in code or "private class" in code or "public static void main" in code:
            return "java"
        elif "#include" in code and ("int main" in code or "void main" in code):
            if "cout" in code or "cin" in code or "::" in code:
                return "c++"
            return "c"
        elif "using System;" in code or "namespace" in code and "{" in code:
            return "c#"
        elif "package " in code or "import " in code and "func " in code:
            return "go"
        elif "func " in code or "struct " in code and "impl " in code:
            return "rust"
        elif "<?php" in code or "namespace " in code and ";" in code:
            return "php"
        elif "require" in code or "def " in code and "end" in code:
            return "ruby"
        elif "<!DOCTYPE html>" in code or "<html>" in code:
            return "html"
        elif "{" in code and "}" in code and ":" in code and not "def " in code and not "function" in code:
            return "css"
        elif "#!/bin/bash" in code or "#!/bin/sh" in code:
            return "bash"
        elif "SELECT" in code.upper() and "FROM" in code.upper():
            return "sql"
        elif "import SwiftUI" in code or "class " in code and "init(" in code:
            return "swift"
        elif "fun " in code or "val " in code or "var " in code and "import kotlin" in code:
            return "kotlin"
        return None

    async def _validate_python(self, code: str) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as temp:
            temp.write(code.encode())
            temp_name = temp.name
        
        try:
            proc = subprocess.Popen(
                ["python", "-m", "py_compile", temp_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = proc.communicate()
            os.unlink(temp_name)
            
            if proc.returncode == 0:
                return {"valid": True}
            else:
                return {"valid": False, "error": stderr}
        except Exception as e:
            try:
                os.unlink(temp_name)
            except:
                pass
            return {"valid": False, "error": str(e)}

    async def _validate_javascript(self, code: str) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".js", delete=False) as temp:
            temp.write(code.encode())
            temp_name = temp.name
        
        try:
            proc = subprocess.Popen(
                ["node", "--check", temp_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = proc.communicate()
            os.unlink(temp_name)
            
            if proc.returncode == 0:
                return {"valid": True}
            else:
                return {"valid": False, "error": stderr}
        except Exception as e:
            try:
                os.unlink(temp_name)
            except:
                pass
            return {"valid": False, "error": f"Could not validate JavaScript: {str(e)}"}

    async def _validate_typescript(self, code: str) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".ts", delete=False) as temp:
            temp.write(code.encode())
            temp_name = temp.name
        
        try:
            proc = subprocess.Popen(
                ["tsc", "--noEmit", temp_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = proc.communicate()
            os.unlink(temp_name)
            
            if proc.returncode == 0:
                return {"valid": True}
            else:
                return {"valid": False, "error": stderr}
        except Exception as e:
            try:
                os.unlink(temp_name)
            except:
                pass
            return {"valid": False, "error": f"Could not validate TypeScript: {str(e)}"}

    async def _validate_java(self, code: str) -> dict:
        # Extract class name from code
        class_pattern = r"public\s+class\s+(\w+)"
        match = re.search(class_pattern, code)
        class_name = match.group(1) if match else "Main"
        
        with tempfile.NamedTemporaryFile(suffix=f".java", delete=False) as temp:
            temp.write(code.encode())
            temp_name = temp.name
        
        try:
            proc = subprocess.Popen(
                ["javac", temp_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = proc.communicate()
            os.unlink(temp_name)
            
            if proc.returncode == 0:
                return {"valid": True}
            else:
                return {"valid": False, "error": stderr}
        except Exception as e:
            try:
                os.unlink(temp_name)
            except:
                pass
            return {"valid": False, "error": f"Could not validate Java: {str(e)}"}

    async def _validate_c(self, code: str) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".c", delete=False) as temp:
            temp.write(code.encode())
            temp_name = temp.name
        
        try:
            proc = subprocess.Popen(
                ["gcc", "-fsyntax-only", temp_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = proc.communicate()
            os.unlink(temp_name)
            
            if proc.returncode == 0:
                return {"valid": True}
            else:
                return {"valid": False, "error": stderr}
        except Exception as e:
            try:
                os.unlink(temp_name)
            except:
                pass
            return {"valid": False, "error": f"Could not validate C: {str(e)}"}

    async def _validate_cpp(self, code: str) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".cpp", delete=False) as temp:
            temp.write(code.encode())
            temp_name = temp.name
        
        try:
            proc = subprocess.Popen(
                ["g++", "-fsyntax-only", temp_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = proc.communicate()
            os.unlink(temp_name)
            
            if proc.returncode == 0:
                return {"valid": True}
            else:
                return {"valid": False, "error": stderr}
        except Exception as e:
            try:
                os.unlink(temp_name)
            except:
                pass
            return {"valid": False, "error": f"Could not validate C++: {str(e)}"}

    async def _validate_csharp(self, code: str) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".cs", delete=False) as temp:
            temp.write(code.encode())
            temp_name = temp.name
        
        try:
            proc = subprocess.Popen(
                ["csc", "/nologo", "/out:nul", "/t:library", temp_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = proc.communicate()
            os.unlink(temp_name)
            
            if proc.returncode == 0:
                return {"valid": True}
            else:
                return {"valid": False, "error": stderr}
        except Exception as e:
            try:
                os.unlink(temp_name)
            except:
                pass
            return {"valid": False, "error": f"Could not validate C#: {str(e)}"}

    async def _validate_go(self, code: str) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".go", delete=False) as temp:
            temp.write(code.encode())
            temp_name = temp.name
        
        try:
            proc = subprocess.Popen(
                ["go", "vet", temp_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = proc.communicate()
            os.unlink(temp_name)
            
            if proc.returncode == 0:
                return {"valid": True}
            else:
                return {"valid": False, "error": stderr}
        except Exception as e:
            try:
                os.unlink(temp_name)
            except:
                pass
            return {"valid": False, "error": f"Could not validate Go: {str(e)}"}

    async def _validate_ruby(self, code: str) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".rb", delete=False) as temp:
            temp.write(code.encode())
            temp_name = temp.name
        
        try:
            proc = subprocess.Popen(
                ["ruby", "-c", temp_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = proc.communicate()
            os.unlink(temp_name)
            
            if proc.returncode == 0:
                return {"valid": True}
            else:
                return {"valid": False, "error": stderr or stdout}
        except Exception as e:
            try:
                os.unlink(temp_name)
            except:
                pass
            return {"valid": False, "error": f"Could not validate Ruby: {str(e)}"}

    async def _validate_php(self, code: str) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".php", delete=False) as temp:
            temp.write(code.encode())
            temp_name = temp.name
        
        try:
            proc = subprocess.Popen(
                ["php", "-l", temp_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = proc.communicate()
            os.unlink(temp_name)
            
            if proc.returncode == 0:
                return {"valid": True}
            else:
                return {"valid": False, "error": stderr or stdout}
        except Exception as e:
            try:
                os.unlink(temp_name)
            except:
                pass
            return {"valid": False, "error": f"Could not validate PHP: {str(e)}"}

    async def _validate_rust(self, code: str) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".rs", delete=False) as temp:
            temp.write(code.encode())
            temp_name = temp.name
        
        try:
            proc = subprocess.Popen(
                ["rustc", "--emit=metadata", "-o", "/dev/null", temp_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = proc.communicate()
            os.unlink(temp_name)
            
            if proc.returncode == 0:
                return {"valid": True}
            else:
                return {"valid": False, "error": stderr}
        except Exception as e:
            try:
                os.unlink(temp_name)
            except:
                pass
            return {"valid": False, "error": f"Could not validate Rust: {str(e)}"}

    async def _validate_bash(self, code: str) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".sh", delete=False) as temp:
            temp.write(code.encode())
            temp_name = temp.name
        
        try:
            proc = subprocess.Popen(
                ["bash", "-n", temp_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = proc.communicate()
            os.unlink(temp_name)
            
            if proc.returncode == 0:
                return {"valid": True}
            else:
                return {"valid": False, "error": stderr}
        except Exception as e:
            try:
                os.unlink(temp_name)
            except:
                pass
            return {"valid": False, "error": f"Could not validate Bash: {str(e)}"}

    async def _validate_html(self, code: str) -> dict:
        # For HTML, we'll just check if it contains valid tags and structure
        # This is a very basic validation - ideally we'd use a proper HTML validator
        basic_errors = []
        
        # Check for missing closing tags
        opening_tags = re.findall(r'<([a-zA-Z0-9]+)[\s>]', code)
        closing_tags = re.findall(r'</([a-zA-Z0-9]+)>', code)
        
        # Simple check for self-closing tags
        self_closing = ['img', 'br', 'hr', 'input', 'meta', 'link', 'source']
        
        for tag in opening_tags:
            if tag.lower() not in self_closing and tag not in closing_tags:
                basic_errors.append(f"Missing closing tag for <{tag}>")
        
        # Check for basic structure
        if "<html" not in code.lower():
            basic_errors.append("Missing <html> tag")
        if "<head" not in code.lower():
            basic_errors.append("Missing <head> tag")
        if "<body" not in code.lower():
            basic_errors.append("Missing <body> tag")
        
        if basic_errors:
            return {"valid": False, "error": "\n".join(basic_errors)}
        return {"valid": True}

    async def _validate_css(self, code: str) -> dict:
        # Basic CSS validation
        basic_errors = []
        
        # Check for unclosed braces
        if code.count('{') != code.count('}'):
            basic_errors.append(f"Mismatched braces: {code.count('{')} opening vs {code.count('}')} closing")
        
        # Check for missing semicolons
        properties = re.findall(r'([a-zA-Z-]+)\s*:\s*([^;{}]+)(?=[;}])', code)
        missing_semicolons = re.findall(r'([a-zA-Z-]+)\s*:\s*([^;{}]+)(?=[}])', code)
        
        if missing_semicolons:
            basic_errors.append("Missing semicolons after property values")
        
        if basic_errors:
            return {"valid": False, "error": "\n".join(basic_errors)}
        return {"valid": True}

    async def _validate_swift(self, code: str) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".swift", delete=False) as temp:
            temp.write(code.encode())
            temp_name = temp.name
        
        try:
            proc = subprocess.Popen(
                ["swift", "-frontend", "-typecheck", temp_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = proc.communicate()
            os.unlink(temp_name)
            
            if proc.returncode == 0:
                return {"valid": True}
            else:
                return {"valid": False, "error": stderr}
        except Exception as e:
            try:
                os.unlink(temp_name)
            except:
                pass
            return {"valid": False, "error": f"Could not validate Swift: {str(e)}"}

    async def _validate_kotlin(self, code: str) -> dict:
        with tempfile.NamedTemporaryFile(suffix=".kt", delete=False) as temp:
            temp.write(code.encode())
            temp_name = temp.name
        
        try:
            proc = subprocess.Popen(
                ["kotlinc", temp_name, "-include-runtime", "-d", "/dev/null"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            _, stderr = proc.communicate()
            os.unlink(temp_name)
            
            if proc.returncode == 0:
                return {"valid": True}
            else:
                return {"valid": False, "error": stderr}
        except Exception as e:
            try:
                os.unlink(temp_name)
            except:
                pass
            return {"valid": False, "error": f"Could not validate Kotlin: {str(e)}"}
            
    async def _validate_sql(self, code: str) -> dict:
        # Basic SQL validation - checking for common syntax errors
        basic_errors = []
        
        # Check for missing semicolons at the end of statements
        statements = [s.strip() for s in code.split(';') if s.strip()]
        if statements and not code.strip().endswith(';'):
            basic_errors.append("SQL statement may be missing ending semicolon")
        
        # Check for balanced parentheses
        if code.count('(') != code.count(')'):
            basic_errors.append(f"Mismatched parentheses: {code.count('(')} opening vs {code.count(')')} closing")
        
        # Check for basic keywords in correct positions
        if re.search(r'SELECT.*FROM.*WHERE\s+ORDER\s+BY', code, re.IGNORECASE):
            basic_errors.append("Incorrect SQL syntax: ORDER BY should come after WHERE")
        
        if re.search(r'INSERT\s+INTO.*VALUES\s+SET', code, re.IGNORECASE):
            basic_errors.append("Incorrect SQL syntax: Cannot use both VALUES and SET in INSERT")
        
        if basic_errors:
            return {"valid": False, "error": "\n".join(basic_errors)}
        return {"valid": True}

def setup(bot):
    bot.add_cog(CodeValidator(bot))
