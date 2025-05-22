import hashlib
import json
import os
import time
from typing import Dict, List, Optional
from flask import current_app
import ollama

class OllamaService():
    def __init__(self):
        self.model_name = "gemma3:12b"
        self.temperature = 0.7
        self.cache_dir = current_app.config['CACHE_DIR']      

    def get_ollama(self):
        return ollama
    
    def get_models(self):
        model_list = ollama.list()
        return model_list.models
    
    def chat(self, model_name, user_input, stream=False):
        messages =  [
            {'role':'system','content':"""
             You are JiM. JiM will assist user with all the knowledge about water, watershed, water in climate,
             water data, river, lakes and everything related to water. If JiM do not know the answer just say 'I dont know.
             Please ask Mr. Krishan Tyagi, Project Manager, WASCA II to include this topic and for any further details'.    
             """},
            {'role':'user','content': user_input}
                     ]
        return ollama.chat(
                    model=model_name,
                    messages=messages,
                    stream=stream
                )
    
    def generate(self, model="gemma3:12b", prompt="You are a helpful assistant", stream = False):
        return ollama.generate(model= model, 
                               prompt=prompt, 
                               stream=stream)
    
    def translate(self, user_input, model="gemma3:12b", stream = False):
        prompt = f"""
        "You are JiM. JiM is a helpful German translator. JiM reviews the text and identifies the language. 
        JiM translates the text to english.  
        JiM will also check the text for any spelling or grammar mistakes and correct them.
        Do not add any addtional comments or explanations. Just Translate. 
        
        text:
        {user_input}
        """
        
        return ollama.generate(model= model, 
                               prompt=prompt, 
                               stream=stream)
        
    def generate_draft_tor(self, context:str, proposal_format:str, model="gemma3:12b", stream=False): 
        prompt = f"""
        You are an expert terms of reference creator with extensive experience in creating sound and perfect terms of references.
        Your task is to create a professional terms of reference based on the provided CONTEXT and FORMAT requirements.
        Use industry best practices and standards in your proposal. Explanations for each heading must be at least one paragraph long
        Ensure your language is precise, professional, and persuasive.
        
        CONTEXT:
        {context}
        
        FORMAT:
        {proposal_format}
        
        Use examples and specific metrics where appropriate.
        Be thorough but concise, focusing on clarity and precision. 
        Do not use bulleted list unless essentially required. 
        Do not provide any other explanation or suggestions other than the format.
        """    
        return ollama.generate(model= model, 
                               prompt=prompt, 
                               stream=stream)
         
    def _cache_key(self, prompt: str, system_prompt: str = '') -> str:
        """Generate a cache key for the given prompts."""
        content = f"{self.model_name}:{prompt}:{system_prompt or ''}:{self.temperature}"
        return hashlib.md5(content.encode()).hexdigest()
    
    def _check_cache(self, cache_key: str) -> Optional[str]:
        """Check if response is in cache."""
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                    # Check if cache is still valid (24 hours)
                    if time.time() - data.get("timestamp", 0) < 86400:
                        # logger.info(f"Cache hit for {cache_key[:8]}")
                        return data.get("response")
            except Exception as e:
                # logger.warning(f"Error reading cache: {str(e)}")
                pass
        return None
    
    def _save_to_cache(self, cache_key: str, response: str) -> None:
        """Save response to cache."""
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
        try:
            with open(cache_file, 'w') as f:
                json.dump({
                    "response": response,
                    "timestamp": time.time()
                }, f)
            # logger.debug(f"Saved to cache: {cache_key[:8]}")
        except Exception as e:
            # logger.warning(f"Error saving to cache: {str(e)}")
            pass
        
    def _generate_response(self, prompt: str, system_prompt: str = ''):
        """Generate a response using Ollama generate API with caching."""
        cache_key = self._cache_key(prompt, system_prompt)
        cached_response = self._check_cache(cache_key)
        if cached_response:
            return cached_response
            
        try:
            response = ollama.generate(
                model=self.model_name,
                prompt=prompt,
                system=system_prompt if system_prompt else "",
                options={"temperature": self.temperature}
            )
            result = response['response']
            self._save_to_cache(cache_key, result)
            return result
        except Exception as e:
            error_msg = f"Error generating response: {str(e)}"
            # logger.error(error_msg)
            # raise LLMException(error_msg)
    
    def _chat_completion(self, messages: List[Dict[str, str]]) -> str:
        """Generate a response using Ollama chat API with caching."""
        # Create a deterministic representation of messages for caching
        messages_str = json.dumps(messages, sort_keys=True)
        cache_key = self._cache_key(messages_str, "")
        cached_response = self._check_cache(cache_key)
        if cached_response:
            return cached_response
            
        try:
            response = ollama.chat(
                model=self.model_name,
                messages=messages,
                options={"temperature": self.temperature}
            )
            result = response['message']['content']
            self._save_to_cache(cache_key, result)
            return result
        
        except Exception as e:
            error_msg = f"Error in chat completion: {str(e)}"
            return error_msg
            # logger.error(error_msg)
            # raise LLMException(error_msg)
            
    def create_terms_of_reference(self, context: str, terms_of_reference_format: str) -> str:
        """Creator agent that drafts the initial terms of reference."""
        system_prompt = """
        You are JiM. Jim is an expert terms of reference creator with extensive experience in creating winning proposals.
        JiM's task is to create a professional terms of reference based on the provided CONTEXT and FORMAT requirements..
        Explanations for each heading must be at least one paragraph long
        Ensure your language is precise, professional, and persuasive.
        """
        
        prompt = f"""
        Create a detailed terms of reference based on the following context:
        
        CONTEXT:
        {context}
        
        FORMAT:
        {terms_of_reference_format}
        
        Use examples and specific metrics where appropriate.
        Be thorough but concise, focusing on clarity and precision. 
        Do not use bulleted list unless essentially required. 
        Do not provide any other explanation or suggestions other than the format.
        """
        
        # logger.info("Creator agent generating initial draft")
        result = self._generate_response(prompt, system_prompt)
        return result if result is not None else ""
    
    def review_terms_of_reference(self, draft_tor: str, context: str, proposal_format: str) -> str:
        """Reviewer agent that reviews the draft terms of reference and provides feedback."""
        messages = [
            {
                "role": "system",
                "content": """
                You are JiM. JiM is an expert terms of reference reviewer with a critical eye for detail and quality.
                JiM's task is to review the DRAFT TERMS OF REFERENCE and provide constructive feedback for improvement.
                Focus on:
                1. Technical accuracy and feasibility
                2. Completeness of information
                3. Clarity and structure
                4. Alignment with ORIGINAL CONTEXT
                5. Persuasiveness and competitive positioning
                6. Potential weaknesses or risks
                7. Format compliance and professionalism based on REQUIRED FORMAT

                Provide specific, actionable feedback that will help improve the proposal.
                Be thorough but constructive in your criticism.
                """
            },
            {
                "role": "user",
                "content": f"""
                Review the following DRAFT TERMS OF REFERENCE:
                
                DRAFT TERMS OF REFERENCE:
                {draft_tor}
                
                ORIGINAL CONTEXT:
                {context}
                
                REQUIRED FORMAT:
                {proposal_format}
                
                Provide detailed, section-by-section feedback on how to improve this proposal.
                For each major section:
                1. Identify strengths
                2. Point out weaknesses or gaps
                3. Suggest specific improvements
                4. Rate each section on a scale of 1-5

                Conclude with an overall assessment and prioritized list of improvements.
                """
            }
        ]
        
        # logger.info("Reviewer agent evaluating proposal")
        return self._chat_completion(messages)
    
    def revise_terms_of_reference(self, draft_tor: str, feedback: str, context: str, proposal_format: str) -> str:
        """Creator agent revises the terms of reference based on feedback."""
        messages = [
            {
                "role": "system",
                "content": """
                You are JiM. JiM is an expert terms of reference creator tasked with revising a proposal based on reviewer feedback.
                JiM's goal is to create a polished, compelling final version that addresses all feedback points
                while maintaining clarity, persuasiveness, and technical accuracy.
                
                Follow these guidelines:
                1. Address all REVIEWER FEEDBACK points thoroughly
                2. Maintain consistent formatting and structure
                3. Ensure technical accuracy and feasibility
                4. Strengthen value propositions and competitive advantages
                5. Maintain a professional, confident tone
                6. Ensure all claims are supported with evidence
                """
            },
            {
                "role": "user",
                "content": f"""
                Revise the following DRAFT TERMS OF REFERENCE based on reviewer feedback:
                
                DRAFT TERMS OF REFERENCE:
                {draft_tor}
                
                REVIEWER FEEDBACK:
                {feedback}
                
                ORIGINAL CONTEXT:
                {context}
                
                REQUIRED FORMAT:
                {proposal_format}
                
                Create a complete, polished final version of the terms of reference that addresses all feedback
                while maintaining the required format. This should be ready for client submission.
                Do not include any meta-comments or explanations about your changes - just produce
                the final proposal text.
                """
            }
        ]
        
        # logger.info("Creator agent revising proposal based on feedback")
        return self._chat_completion(messages)
    
    def evaluate_terms_of_reference(self, final_proposal: str, context: str, proposal_format: str) -> str:
        """Evaluator agent that scores the final proposal on a scale of 1-5."""
        messages = [
            {
                "role": "system",
                "content": """
                You are JiM. JiM is an expert evaluator of TERMS OF REFERENCE with extensive experience in
                reviewing proposals for major organizations and government agencies.
                
                Your task is to provide an objective, thorough evaluation of the TERMS OF REFERENCE on a scale of 1-5
                (1 being poor, 5 being excellent). Evaluate the TERMS OF REFERENCE based on:
                
                1. Technical merit and feasibility
                2. Completeness and attention to detail
                3. Alignment with REQUIRED FORMAT and ORIGINAL CONTEXT
                4. Clarity and organization
                5. Persuasiveness and value proposition
                6. Risk assessment and mitigation
                7. Overall quality and professionalism
                """
            },
            {
                "role": "user",
                "content": f"""
                Evaluate the following final TERMS OF REFERENCE:
                
                TERMS OF REFERENCE:
                {final_proposal}
                
                ORIGINAL CONTEXT:
                {context}
                
                REQUIRED FORMAT:
                {proposal_format}
                
                Provide a comprehensive evaluation with:
                
                SCORE: [1-5]
                
                STRENGTHS:
                - [List at least 3 specific strengths]
                
                WEAKNESSES:
                - [List any weaknesses or areas for improvement]
                
                SECTION RATINGS:
                - Executive Summary: [1-5]
                - Technical Approach: [1-5]
                - Implementation Plan: [1-5]
                - Technical Specifications: [1-5]
                - Risk Assessment: [1-5]
                - Budget and Resources: [1-5]
                - Success Criteria: [1-5]
                
                OVERALL ASSESSMENT:
                [Provide a detailed justification for your overall score and final recommendations]
                """
            }
        ]
        
        # logger.info("Evaluator agent scoring final proposal")
        return self._chat_completion(messages)