# Garment image provenance

The 40 garment photos in this directory (`<id>.jpg`) come from the public
Kaggle dataset **[Fashion Product Images Dataset](https://www.kaggle.com/datasets/paramaggarwal/fashion-product-images-dataset)**
(`paramaggarwal/fashion-product-images-dataset`).

- **Metadata licence**: MIT (per the dataset's Kaggle listing).
- **Product photography**: the images themselves originate from
  **Myntra** (myntra.com), an Indian e-commerce fashion retailer; the
  dataset's `images.csv` maps each item id to its original
  `assets.myntassets.com` product-shot URL. We downloaded, resized
  (long side capped at 1024px), and re-hosted a curated ~40-item subset
  here rather than hot-linking those URLs at runtime.
- **How the subset was chosen and built**: see
  `backend/scripts/build_catalog.py`, which is runnable end-to-end and
  reproduces this catalog (network access required, no Kaggle
  authentication needed). It documents its own selection, colour-
  extraction, and metadata-derivation logic inline.
- **Scope of use**: images and metadata here are used only for a
  non-commercial hackathon prototype (an in-store styling kiosk demo),
  reproducing the dataset's stated licence terms for the metadata and
  identifying the photography's original source (Myntra) rather than
  claiming it as original work.
