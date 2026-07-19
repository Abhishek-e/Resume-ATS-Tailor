const express = require('express');
const cors = require('cors');
const path = require('path');
const { GoogleGenerativeAI } = require('@google/generative-ai');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(express.static('public'));

// 🔑 Get API key from environment variable
const API_KEY = process.env.GEMINI_API_KEY;

if (!API_KEY) {
  console.error('❌ GEMINI_API_KEY is not set in environment variables');
  if (process.env.NODE_ENV === 'production') {
    console.warn('⚠️  Running without Gemini API key - some features will not work');
  }
}

// Initialize Gemini if API key exists
let genAI = null;
if (API_KEY) {
  genAI = new GoogleGenerativeAI(API_KEY);
}

// API endpoint for tailoring resume
app.post('/api/tailor-resume', async (req, res) => {
  try {
    if (!genAI) {
      throw new Error('Gemini API not configured. Please set GEMINI_API_KEY.');
    }

    const { resumeText, jobDescriptions } = req.body;
    
    if (!resumeText || resumeText.trim() === '') {
      return res.status(400).json({ error: 'Resume text is required' });
    }

    // ✅ FIX: Use the correct model name - 'gemini-1.5-pro' or 'gemini-1.5-flash'
    // For the latest model, use 'gemini-1.5-pro' or 'gemini-1.5-flash'
    const model = genAI.getGenerativeModel({ 
      model: 'gemini-3.5-flash' // Changed from 'gemini-pro' to 'gemini-1.5-pro'
    });

    const prompt = `
      You are an expert ATS (Applicant Tracking System) resume optimizer with 10+ years of experience in HR tech.
      
      Original Resume:
      ${resumeText}
      
      Available Job Positions:
      ${jobDescriptions || 'General tech positions'}
      
      Please optimize this resume for ATS systems by:
      1. Identifying and incorporating relevant keywords from the job descriptions
      2. Using strong action verbs and quantifiable achievements
      3. Optimizing the format for ATS parsing (clear sections, standard headings)
      4. Removing any graphics, tables, or formatting that might confuse ATS
      5. Highlighting relevant skills and experience
      6. Adding a professional summary section
      7. Ensuring proper keyword density for top ATS ranking
      
      Return ONLY the optimized resume text with clear section headers (Summary, Skills, Experience, Education, Certifications).
      Do not add any additional commentary or explanation.
    `;

    const result = await model.generateContent({
      contents: [{
        parts: [{
          text: prompt
        }]
      }],
      generationConfig: {
        temperature: 0.7,
        maxOutputTokens: 1500,
        topP: 0.8,
        topK: 40,
      }
    });

    const response = await result.response;
    const tailoredText = response.text();

    if (!tailoredText || tailoredText.trim() === '') {
      throw new Error('Empty response from Gemini API');
    }

    res.json({ 
      success: true, 
      tailored: tailoredText 
    });

  } catch (error) {
    console.error('Error in /api/tailor-resume:', error);
    res.status(500).json({ 
      error: error.message || 'Failed to tailor resume' 
    });
  }
});

// API endpoint for generating CV from keywords
app.post('/api/generate-cv', async (req, res) => {
  try {
    if (!genAI) {
      throw new Error('Gemini API not configured. Please set GEMINI_API_KEY.');
    }

    const { jobTitle, keywords, currentResume } = req.body;
    
    if (!jobTitle || !keywords || keywords.length === 0) {
      return res.status(400).json({ error: 'Job title and keywords are required' });
    }

    // ✅ FIX: Use the correct model name
    const model = genAI.getGenerativeModel({ 
      model: 'Gemini 3.5 Flash' // Changed from 'gemini-pro' to 'gemini-1.5-pro'
    });

    const prompt = `
      You are a professional CV writer specializing in creating ATS-optimized resumes.
      
      Job Title: ${jobTitle}
      Required Keywords: ${keywords.join(', ')}
      ${currentResume ? `Current Resume (for reference): ${currentResume}` : ''}
      
      Create a professional, ATS-friendly CV that:
      1. Incorporates ALL the provided keywords naturally
      2. Has a clean, well-structured format
      3. Includes sections: Professional Summary, Core Competencies, Professional Experience (with 2-3 bullet points each), Education, and Certifications
      4. Uses strong action verbs and quantifiable achievements
      5. Is tailored specifically for the ${jobTitle} role
      6. Is between 400-600 words
      
      Return ONLY the CV text with clear section headers. Do not add any additional commentary.
    `;

    const result = await model.generateContent({
      contents: [{
        parts: [{
          text: prompt
        }]
      }],
      generationConfig: {
        temperature: 0.8,
        maxOutputTokens: 1500,
        topP: 0.9,
        topK: 40,
      }
    });

    const response = await result.response;
    const cvText = response.text();

    if (!cvText || cvText.trim() === '') {
      throw new Error('Empty response from Gemini API');
    }

    res.json({ 
      success: true, 
      cv: cvText 
    });

  } catch (error) {
    console.error('Error in /api/generate-cv:', error);
    res.status(500).json({ 
      error: error.message || 'Failed to generate CV' 
    });
  }
});

// Health check endpoint
app.get('/api/health', (req, res) => {
  res.json({ 
    status: 'OK', 
    message: 'Gemini API proxy is running',
    apiKeyConfigured: !!API_KEY,
    environment: process.env.NODE_ENV || 'development'
  });
});

// Serve the main HTML page
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'index.html'));
});

// Start server
app.listen(PORT, '0.0.0.0', () => {
  console.log(`🚀 Server running on http://localhost:${PORT}`);
  console.log(`✅ Gemini API is ${API_KEY ? 'configured' : 'MISSING API KEY!'}`);
  console.log(`🌍 Environment: ${process.env.NODE_ENV || 'development'}`);
});
