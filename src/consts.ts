// Place any global data in this file.
// You can import this data from anywhere in your site by using the `import` keyword.

export const SITE_TITLE = 'Испания, ¿qué pasa?';
export const SITE_DESCRIPTION = 'Информационный портал для русскоязычных мигрантов в Испании';
export const SITE_URL = 'https://spain-que-pasa.com';

// Категории новостей
export const CATEGORIES = {
	migration: {
		name: 'Миграция',
		description: 'Новости о миграционных процессах, визах и документах',
		icon: '🛂',
		color: 'blue'
	},
	policy: {
		name: 'Политика',
		description: 'Политические новости и изменения в законодательстве',
		icon: '🏛️',
		color: 'red'
	},
	weather: {
		name: 'Погода',
		description: 'Прогнозы погоды и климатические новости',
		icon: '🌤️',
		color: 'yellow'
	},
	health: {
		name: 'Здоровье',
		description: 'Новости здравоохранения и медицинские советы',
		icon: '🏥',
		color: 'green'
	},
	crime: {
		name: 'Криминал',
		description: 'Криминальные новости и безопасность',
		icon: '🚔',
		color: 'orange'
	},
	events: {
		name: 'События',
		description: 'Культурные события, праздники и мероприятия',
		icon: '🎉',
		color: 'purple'
	},
	lifehacks: {
		name: 'Лайфхаки',
		description: 'Полезные советы для жизни в Испании',
		icon: '💡',
		color: 'teal'
	},
	education: {
		name: 'Образование',
		description: 'Новости образования и обучения',
		icon: '🎓',
		color: 'indigo'
	},
	transport: {
		name: 'Транспорт',
		description: 'Новости транспорта и дорожного движения',
		icon: '🚇',
		color: 'gray'
	},
	economy: {
		name: 'Экономика',
		description: 'Экономические новости и финансы',
		icon: '💰',
		color: 'emerald'
	}
} as const;

export type CategoryKey = keyof typeof CATEGORIES; 