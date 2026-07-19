const express = require('express');
const cors = require('cors');
const path = require('path');
const { GoogleGenerativeAI, HarmCategory, HarmBlockThreshold } = require('@google/generative-ai');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(express.static('public'));

// Get API key from environment variable
const API_KEY = process.env.GEMINI_API_KEY;

if (!API_KEY) {
  console.error('❌ GEMINI_API_KEY is not set in environment variables');
  if (process.env.NODE_ENV === 'production') {
    console.warn('⚠️ Running without Gemini API key - some features will not work');
  }
}

// Initialize Gemini with safety settings
let genAI = null;
if (API_KEY) {
  try {
    genAI = new GoogleGenerativeAI(API_KEY);
    console.log('✅ Gemini API initialized successfully');
  } catch (error) {
    console.error('❌ Failed to initialize Gemini:', error.message);
  }
}

// Helper function to generate content with fallback models
async function generateWithFallback(prompt, config) {
  if (!genAI) {
    throw new Error('Gemini API not configured. Please check your API key.');
  }

  // Try different model names (in order of preference)
  const modelsToTry = [
    'gemini-3.1-flash-lite',  // ✅ Latest model you specified
    'gemini-1.5-flash',
    'gemini-1.5-pro',
    'gemini-pro'
  ];

  let lastError = null;

  for (const modelName of modelsToTry) {
    try {
      console.log(`🔄 Trying model: ${modelName}`);
      
      const model = genAI.getGenerativeModel({ 
        model: modelName,
        safetySettings: [
          {
            category: HarmCategory.HARM_CATEGORY_HARASSMENT,
            threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
          },
          {
            category: HarmCategory.HARM_CATEGORY_HATE_SPEECH,
            threshold: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
          },
        ]
      });

      const result = await model.generateContent({
        contents: [{
          parts: [{
            text: prompt
          }]
        }],
        generationConfig: {
          temperature: config.temperature || 0.7,
          maxOutputTokens: config.maxOutputTokens || 1500,
          topP: config.topP || 0.8,
          topK: config.topK || 40,
        }
      });

      const response = await result.response;
      const text = response.text();
      
      if (text && text.trim()) {
        console.log(`✅ Success with model: ${modelName}`);
        return text;
      } else {
        throw new Error('Empty response from model');
      }
      
    } catch (error) {
      console.log(`❌ Failed with ${modelName}: ${error.message}`);
      lastError = error;
      
      // If it's a 404, continue to next model
      if (error.message.includes('404') || error.message.includes('not found')) {
        continue;
      }
      
      // If it's an API key error, break immediately
      if (error.message.includes('API key') || error.message.includes('auth')) {
        break;
      }
    }
  }

  throw lastError || new Error('All models failed to generate content');
}

// API endpoint for tailoring resume
app.post('/api/tailor-resume', async (req, res) => {
  try {
    if (!genAI) {
      throw new Error('Gemini API not configured. Please set GEMINI_API_KEY in environment variables.');
    }

    const { resumeText, jobDescriptions } = req.body;
    
    if (!resumeText || resumeText.trim() === '') {
      return res.status(400).json({ error: 'Resume text is required' });
    }

    console.log('📝 Tailoring resume for job descriptions:', jobDescriptions);

    const prompt = `
      You are an expert ATS (Applicant Tracking System) resume optimizer.
      
      Original Resume:
      ${resumeText}
      
      Job Context (Available positions):
      ${jobDescriptions || 'General tech positions'}
      
      Task: Optimize this resume for ATS systems.
      
      Instructions:
      1. Identify and incorporate relevant keywords from the job descriptions
      2. Use strong action verbs and quantifiable achievements
      3. Format with clear sections: Summary, Skills, Experience, Education
      4. Remove any formatting that might confuse ATS
      5. Highlight relevant skills and experience
      6. Add a professional summary at the top
      
      Return ONLY the optimized resume text with clear section headers.
      Do not add any extra commentary or explanation.
    `;

    const config = {
      temperature: 0.7,
      maxOutputTokens: 1500,
      topP: 0.8,
      topK: 40,
    };

    const tailoredText = await generateWithFallback(prompt, config);

    res.json({ 
      success: true, 
      tailored: tailoredText 
    });

  } catch (error) {
    console.error('❌ Error in /api/tailor-resume:', error);
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

    console.log('📄 Generating CV for:', jobTitle);

    const prompt = `
      Create a professional, ATS-friendly CV.
      
      Job Title: ${jobTitle}
      Required Keywords: ${keywords.join(', ')}
      ${currentResume ? `Current Resume (for reference, use as base): ${currentResume}` : ''}
      
      Instructions:
      1. Incorporate ALL the provided keywords naturally
      2. Use a clean, professional format
      3. Include these sections:
         - Professional Summary (3-4 sentences)
         - Core Competencies (bullet points with keywords)
         - Professional Experience (2-3 roles with achievements)
         - Education
         - Certifications (if relevant)
      4. Use strong action verbs and quantifiable achievements
      5. Tailor specifically for the ${jobTitle} role
      6. Keep it between 400-600 words
      
      Return ONLY the CV text with clear section headers.
      Do not add any extra commentary.
    `;

    const config = {
      temperature: 0.8,
      maxOutputTokens: 1500,
      topP: 0.9,
      topK: 40,
    };

    const cvText = await generateWithFallback(prompt, config);

    res.json({ 
      success: true, 
      cv: cvText 
    });

  } catch (error) {
    console.error('❌ Error in /api/generate-cv:', error);
    res.status(500).json({ 
      error: error.message || 'Failed to generate CV' 
    });
  }
});

// Debug endpoint to test API connection
app.get('/api/test', async (req, res) => {
  try {
    if (!genAI) {
      throw new Error('Gemini API not configured');
    }

    // Try a simple test prompt with the correct model
    const testPrompt = "Say 'API is working' in one sentence.";
    const result = await generateWithFallback(testPrompt, {
      temperature: 0.1,
      maxOutputTokens: 50
    });

    res.json({
      success: true,
      message: 'API is working',
      response: result,
      apiKeyConfigured: !!API_KEY,
      models: ['gemini-3.1-flash-lite', 'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']
    });
  } catch (error) {
    res.status(500).json({
      success: false,
      error: error.message,
      apiKeyConfigured: !!API_KEY
    });
  }
});

// Health check endpoint
app.get('/api/health', (req, res) => {
  res.json({ 
    status: 'OK', 
    message: 'Gemini API proxy is running',
    apiKeyConfigured: !!API_KEY,
    environment: process.env.NODE_ENV || 'development',
    timestamp: new Date().toISOString()
  });
});

// Serve the main HTML page
app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname,'index.html'));
});

// Error handling middleware
app.use((err, req, res, next) => {
  console.error('❌ Unhandled error:', err);
  res.status(500).json({
    error: 'Internal server error',
    message: err.message
  });
});

// Start server
app.listen(PORT, '0.0.0.0', () => {
  console.log(`\n🚀 Server running on http://localhost:${PORT}`);
  console.log(`📡 API endpoint: http://localhost:${PORT}/api/tailor-resume`);
  console.log(`🔍 Test endpoint: http://localhost:${PORT}/api/test`);
  console.log(`✅ Gemini API ${API_KEY ? 'configured ✅' : 'MISSING ❌'}`);
  console.log(`🌐 Models available: gemini-3.1-flash-lite, gemini-1.5-flash, gemini-1.5-pro, gemini-pro`);
  console.log(`\n💡 To test the API, visit: http://localhost:${PORT}/api/test\n`);
});
