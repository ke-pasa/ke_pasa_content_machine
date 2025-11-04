import { defineCollection, z } from 'astro:content';
import { glob } from 'astro/loaders';

// Базовая схема для всех коллекций
const baseSchema = ({ image }: { image: any }) =>
	z.object({
		title: z.string(),
		description: z.string(),
		pubDate: z.coerce.date(),
		updatedDate: z.coerce.date().optional(),
		image: image().optional(),
		tags: z.array(z.string()),
		slug: z.string().optional(),
		category: z.string().optional(),
		author: z.string().optional(),
		layout: z.string().optional(),
		seo: z.object({
			title: z.string().optional(),
			description: z.string().optional(),
			keywords: z.array(z.string()).optional(),
		}).optional(),
		telegram_post: z.string().optional(),
	});

const news = defineCollection({
	loader: glob({ base: './src/content/news', pattern: '**/*.{md,mdx}' }),
	schema: baseSchema,
});

const articles = defineCollection({
	loader: glob({ base: './src/content/articles', pattern: '**/*.{md,mdx}' }),
	schema: baseSchema,
});

const guides = defineCollection({
	loader: glob({ base: './src/content/guides', pattern: '**/*.{md,mdx}' }),
	schema: baseSchema,
});

const legal = defineCollection({
	loader: glob({ base: './src/content/legal', pattern: '**/*.{md,mdx}' }),
	schema: baseSchema,
});

const catalog = defineCollection({
	loader: glob({ base: './src/content/catalog', pattern: '**/*.{md,mdx}' }),
	schema: baseSchema,
});

export const collections = { news, articles, guides, legal, catalog }; 