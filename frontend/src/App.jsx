import React, { useEffect } from "react";
import { BrowserRouter as Router, Routes, Route, useLocation } from "react-router-dom";
import Header from "./components/Header";
import Hero from "./components/Hero";
import Features from "./components/Features";
import HowItWorks from "./components/HowItWorks";
import Testimonials from "./components/Testimonials";
import Pricing from "./components/Pricing";
import CTA from "./components/CTA";
import Footer from "./components/Footer";
//import ReceiptDropUploader from './components/ReceiptDropUploader';
//import SignInPage from "./components/SignInPage";
import FileDropUploader from "./components/FileDropUploader";
import ReceiptDropUploaderWithPreview from "./components/ReceiptDropUploaderWithPreview";


import "./App.css";
import "@fortawesome/fontawesome-free/css/all.min.css";

function FooterConditional() {
  const location = useLocation();
  // Show footer only on home page
  if (location.pathname === "/") {
    return <Footer />;
  }
  return null;
}

function App() {
  // Smooth scroll for anchor links
  useEffect(() => {
    const handler = (e) => {
      const href = e.target.getAttribute("href");
      if (href && href.startsWith("#")) {
        e.preventDefault();
        const el = document.querySelector(href);
        if (el) el.scrollIntoView({ behavior: "smooth" });
      }
    };
    document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
      anchor.addEventListener("click", handler);
    });
    return () => {
      document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
        anchor.removeEventListener("click", handler);
      });
    };
  }, []);

  return (
    <Router>
      <Header />
      <Routes>
        <Route
          path="/"
          element={
            <>
              <Hero />
              <Features />
              <HowItWorks />
              <Testimonials />
              <Pricing />
              <CTA />
            </>
          }
        />
        <Route path="/file" element={<ReceiptDropUploaderWithPreview />} />
                {/* <Route path="/file" element={<FileDropUploader />} /> */}

      </Routes>
      <FooterConditional />
     </Router>
  );
}

export default App;