package town

import "fmt"

type Town struct {
	Name string
}

func NewTown(name string) *Town {
	return &Town{Name: name}
}

func (t *Town) Greet() string {
	return fmt.Sprintf("Welcome to %s", t.Name)
}
