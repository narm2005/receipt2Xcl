import React, { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';

export default function ReceiptDropUploader() {
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [isUploading, setIsUploading] = useState(false);

  const onDrop = useCallback((acceptedFiles) => {
    const selectedFile = acceptedFiles[0];
    if (selectedFile) {
      setFile(selectedFile);
      setPreviewUrl(URL.createObjectURL(selectedFile));
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'image/*': [],
      'application/pdf': [],
    },
    multiple: false,
  });

  const handleSubmit = async () => {
    if (!file) return alert("Please upload a receipt first.");

    setIsUploading(true);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('http://localhost:8000/upload', {
        method: 'POST',
        body: formData,
      });

      const result = await response.json();
      console.log('Upload successful:', result);
      alert('Upload successful!');
    } catch (error) {
      console.error('Error uploading:', error);
      alert('Upload failed.');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="max-w-md mx-auto mt-10 p-6 border-2 border-dashed rounded-xl text-center bg-white shadow-md">
      <h2 className="text-xl font-semibold mb-4">Try Now – Upload a Receipt</h2>

      <div
        {...getRootProps()}
        className={`cursor-pointer p-8 rounded-md border-2 ${
          isDragActive ? 'border-blue-500 bg-blue-50' : 'border-gray-300 bg-gray-50'
        }`}
      >
        <input {...getInputProps()} />
        {
          isDragActive ? (
            <p className="text-blue-600">Drop the file here...</p>
          ) : (
            <p className="text-gray-700">
              Drag and drop a receipt here, or <span className="text-blue-600 underline">browse</span>
            </p>
          )
        }
      </div>

      {file && (
        <div className="mt-4">
          <p className="text-sm text-gray-700">{file.name}</p>
          {previewUrl && file.type.startsWith('image') && (
            <img
              src={previewUrl}
              alt="Preview"
              className="mt-2 max-h-64 mx-auto rounded shadow"
            />
          )}
          <button
            onClick={handleSubmit}
            disabled={isUploading}
            className="mt-4 px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700"
          >
            {isUploading ? 'Uploading...' : 'Submit'}
          </button>
        </div>
      )}
    </div>
  );
}
