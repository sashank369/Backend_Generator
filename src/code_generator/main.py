#!/usr/bin/env python
from random import randint
from typing import Optional
from pydantic import BaseModel
from crewai.flow.flow import Flow, listen, start,router,or_
import shutil
import json
from code_generator.crews.File_Writter.File_writer import FileWriter
from code_generator.crews.Validate_Layer.Validate_Layer import ValidateLayer
from code_generator.crews.api_parser.api_parser import ApiParser
from code_generator.crews.Model_Layer.Model_Layer import ModelLayer
from code_generator.crews.evaluate_api_parser.evaluate_api_parser import EvaluateApiParser
from code_generator.crews.code_fix.code_fix import Code_fix
import requests
import zipfile
import os
import openai
from typing import Dict
import subprocess
import re

# Load API key from environment variable    
openai.api_key = os.getenv("OPEN_API_KEY")


class CodeGeneratorState(BaseModel):
    project_name: str = ""
    package_name: str = ""
    dependencies: str = ""
    java_version: int = 11
    language: str = ""
    build_type:str='maven'
    boot_version:str='3.3.0'
    base_url:str = "https://start.spring.io/starter.zip"
    api_parser_result: dict = {}
    Generated_code_result: Dict[str, Dict[str, str]] = {}
    folder_path: str = ""
    parser_evaluator_feedback:Optional[str]=""
    parser_valid:bool=False
    parser_evaluator_count:int=0
    build_output:Optional[str]=""



class CodeGenerator(Flow[CodeGeneratorState]):

#-----------------------------------------------------------------------------------------------------------------------

#Intialization (Taking input from user for creating spring boot boiler plate code)

    @start()
    def Intialization(self):
        print("Provide the details")
        self.state.project_name = input("Enter the project name: ")
        self.state.package_name = input("Enter the package name (default com.example): ")
        self.state.dependencies = input("Enter the dependencies (comma separated, e.g., web,jpa): ").split(',')
        self.state.java_version = input("Enter Java version (default 11): ") or '11'
        self.state.language = input("Enter language (java/kotlin, default java): ") or 'java'



# -----------------------------------------------------------------------------------------------------------------------

#Parsing the API

    @listen(or_(Intialization,"retry"))
    def api_parser(self):
        print("parsing the api")
        result = (
            ApiParser()
            .crew()
            .kickoff()
        )

        # print("api result: ", result.raw)
        self.state.api_parser_result = result.raw  # Save the result in state
        print("API parsed successfully and stored in state.")


#-----------------------------------------------------------------------------------------------------------------------

#Evaluating the API parser result

    @router(api_parser)
    def evaluate_api(self):
        if self.state.parser_evaluator_count >3:
            return "max_retry"
        # Evaluate the result of the API parser
        result=EvaluateApiParser().crew().kickoff(inputs={"api_parser_result":self.state.api_parser_result})
        self.state.parser_valid=result["parser_valid"]
        self.state.parser_evaluator_feedback=result["parser_evaluator_feedback"]
        
        # print("parser_valid",self.state.parser_valid)
        # print("parser_evaluator_feedback",self.state.parser_evaluator_feedback)
        self.state.parser_evaluator_count+=1
        
        if self.state.parser_valid:
            return "completed"
        return "retry"




#-----------------------------------------------------------------------------------------------------------------------

# Generating the boiler plate Spring Boot project.

    @listen(or_("completed","max_retry"))
    def generate_spring_boot_project(self):
        params = {
            'type': f'{self.state.build_type}-project',
            'language': self.state.language,
            'javaVersion': self.state.java_version,
            'dependencies': ','.join(self.state.dependencies),
            'artifactId': self.state.project_name,
            'groupId': self.state.package_name,
            'bootVersion': self.state.boot_version
        }

        print(params)
        response = requests.get(self.state.base_url, params=params)
        print("Response Status Code:", response.status_code)
        print("Response Content:", response.text)

        if response.status_code == 200:
            zip_file_path = f'{self.state.project_name}.zip'
            with open(f'{self.state.project_name}.zip', 'wb') as file:
                file.write(response.content)
            if not os.path.exists(self.state.project_name):
                os.makedirs(self.state.project_name)

            # Unzip the file into the specified folder
            with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                zip_ref.extractall(self.state.project_name)
            
            # Remove the original ZIP file after extracting
            os.remove(zip_file_path)
            print(f"Unzipped the project to: {self.state.project_name}")
            return f"Spring Boot project {self.state.project_name} created successfully!"
        else:
            return "Failed"
        


#-----------------------------------------------------------------------------------------------------------------------

# Configuring the application properties

    @listen(generate_spring_boot_project)
    def configure_application_properties(self):

        # properties_content = os.getenv("SPRING_BOOT_PROPERTIES", "")
    
        # # Replace escape sequences with actual newlines
        # properties_content = properties_content.replace("\\n", "\n")
        properties_content = """spring.datasource.url=jdbc:h2:mem:testdb
spring.datasource.driverClassName=org.h2.Driver
spring.datasource.username=sa
spring.datasource.password=password
spring.jpa.database-platform=org.hibernate.dialect.H2Dialect
spring.h2.console.enabled=true
"""

        properties_file_path = os.path.join(self.state.project_name, "src", "main", "resources", "application.properties")

        if not os.path.exists(os.path.dirname(properties_file_path)):
            os.makedirs(os.path.dirname(properties_file_path))

        with open(properties_file_path, 'w') as file:
            file.write(properties_content)

        print(f"application.properties configured successfully at {properties_file_path}")

    
    

#-----------------------------------------------------------------------------------------------------------------------

#Generating the whole application 

    @router(configure_application_properties)
    def SpringBootApplication(self):
        print("Generating model")
        # print("API Result: ", self.state.api_parser_result)
        file_path = "api_parser_result.md"

        # Write the API result to the file
        with open(file_path, "w") as file:
            file.write(f"api parser result: {self.state.api_parser_result}\n")

        # Example base path
        base_path = os.path.join(os.path.abspath(self.state.project_name), "src", "main", "java")
        # Convert package name to directory path
        package_path = self.state.package_name.replace('.', os.sep)
        # Full path to the models directory
        models_path = os.path.join(base_path, package_path,self.state.project_name)
        print ("models_path",models_path)
        print(os.path.exists(models_path))
        if os.path.exists(models_path):
            print(f"Cleaning existing directory contents: {models_path}")
        
            # Delete only contents inside models_path, but not the folder itself
            for filename in os.listdir(models_path):
                file_path = os.path.join(models_path, filename)
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path)  # Delete subdirectories
            
        self.state.folder_path = models_path
        print(f"Models directory path: {models_path}")
        kickoff_inputs = {
            'api_parser_result': self.state.api_parser_result,
            'project_name': self.state.project_name,
            'package_name': self.state.package_name,
            'models_path': models_path,
            # 'feedback':self.state.build_output
        }    

        result = ModelLayer().crew().kickoff(inputs=kickoff_inputs)

        print("Model result: ", result.raw)
        self.state.Generated_code_result = result.raw  # Save the result in state
        print("Entity Model successfully and stored in state.")


        # self.state.Generated_code_result = result.raw  
    
        # file_path = "Generated_code_result.json"
        # with open(file_path, "w") as file:
        #     json.dump(self.state.Generated_code_result, file, indent=4)


# -----------------------------------------------------------------------------------------------------------------------

#Output Validator

    # @listen(SpringBootApplication)
    # def validate_output(self):
    #     print("Validating the output")
  
    #     kickoff_inputs = {
    #         'api_parser_result': self.state.api_parser_result,
    #         'project_name': self.state.project_name,
    #         'package_name': self.state.package_name,
    #         'models_path': self.state.folder_path,
    #         'code_output': self.state.code_output,
    #     }

        

    #     result = ValidateLayer().crew().kickoff(inputs=kickoff_inputs)

    #     print("Model result: ", result.raw)
    #     self.state.Generated_code_result = result.raw  # Save the result in state
    #     print("Entity Model successfully and stored in state.")





# -----------------------------------------------------------------------------------------------------------------------
#file writter crew

    # @listen(validate_output)
    # def File_writter(self):
    #     print("Writting the code into the files")

    #     kickoff_inputs = {
    #         'api_parser_result': self.state.api_parser_result,
    #         'project_name': self.state.project_name,
    #         'package_name': self.state.package_name,
    #         'models_path': self.state.folder_path,
    #         'code_output': self.state.code_output,
    #     }

        

    #     result = FileWriter().crew().kickoff(inputs=kickoff_inputs)

    #     print("Model result: ", result.raw)
    #     self.state.Generated_code_result = result.raw  # Save the result in state
    #     print("Entity Model successfully and stored in state.)

# -----------------------------------------------------------------------------------------------------------------------
    
#Building the code 

    # @router(or_(SpringBootApplication,"buildfix"))
    # def build_and_run_springboot(self):
    #     try:
    #         project_directory = os.path.abspath(self.state.project_name)
    #         print(f"Project directory: {project_directory}")
    #         # Navigate to the Spring Boot project directory
    #         if os.path.exists(project_directory):
    #             os.chdir(project_directory)
    #             print("Directory exists:", os.listdir(project_directory))
    #         else:
    #             print("Directory does not exist:", project_directory)
    #             return
            
    #         # Build the project
    #         build_command = ["mvn", "clean", "package"]
    #         build_process=subprocess.run(build_command,stdout=subprocess.PIPE, stderr=subprocess.PIPE,shell=True)
    #         if build_process.returncode == 0:
    #             print("Build Success!")
    #         else:
    #             self.state.build_output=build_process.stdout.decode()
    #             error_log = self.state.build_output
    #             print("Build Error Log:", error_log)
    #             error_pattern = r"\[ERROR\]\s*(.*\.java):\[(\d+),(\d+)\]\s*(.*)"  # Matches error lines
    #             errors = re.findall(error_pattern, error_log)
    #             print("Build Output:", errors)
                
    #             # Printing thr errors paths and the message associated with it
    #             for file_path, line, col, error_msg in errors:
    #                 print(f"Fixing error in: {file_path} at line {line}, col {col},error message: {error_msg}")
    #             return "buildfail"

    #         # Run the built JAR file
    #         jar_file = f"target/{self.state.project_name}-0.0.1-SNAPSHOT.jar"  # Adjust according to your project
    #         run_command = ["java", "-jar", jar_file]
    #         subprocess.Popen(run_command,shell=True)

    #         print("Spring Boot application is running...")
    #     except subprocess.CalledProcessError as e:
    #         print(f"Error during build or execution: {e}")
    #     except FileNotFoundError as e:
    #         print(f"Directory not found: {project_directory}. Please check the path.")
    #     except Exception as e:
    #         print(f"Unexpected error: {e}")
            
    # @router("buildfail")
    # def buildfail(self):
    #     result=Code_fix().crew().kickoff(inputs={"build_output":self.state.build_output})
    #     print(result)
    #     return"buildfix"


def kickoff():
    Code_generator_flow = CodeGenerator()
    Code_generator_flow.kickoff()


def plot():
    Code_generator_flow = CodeGenerator()
    Code_generator_flow.plot()


if __name__ == "__main__":
    kickoff()
